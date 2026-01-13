#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <SoftwareSerial.h>

// Pin Definitions
#define GPS_RX_PIN 3
#define GPS_TX_PIN 2

// Servo Constants
#define SERVOMIN 102
#define SERVOMAX 512
#define SERVO_FREQ 50

// System Limits
#define AZ_MIN 0
#define AZ_MAX 180
#define EL_MIN 20
#define EL_MAX 45
#define PARK_AZ 90
#define PARK_EL 20

// Timing
#define WATCHDOG_TIMEOUT 120000    // 2 minutes
#define GPS_READ_TIMEOUT 45000     // 45 seconds
#define MOVEMENT_TIMEOUT 5000      // 5 seconds max for servo movement
#define HEARTBEAT_INTERVAL 30000   // 30 seconds

// System States
enum State { 
  STATE_IDLE, 
  STATE_TRACKING, 
  STATE_WATCHDOG, 
  STATE_PARKED, 
  STATE_GETTING_GPS,
  STATE_MOVING,
  STATE_WAITING_FOR_ACK
};

// Non-blocking timer structure
struct Timer {
  unsigned long startTime;
  unsigned long duration;
  bool active;
  
  void start(unsigned long d) {
    startTime = millis();
    duration = d;
    active = true;
  }
  
  bool isDone() {
    if (!active) return false;
    if (millis() - startTime >= duration) {
      active = false;
      return true;
    }
    return false;
  }
  
  void stop() {
    active = false;
  }
};

// Components
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);

// System Variables
State currentState = STATE_PARKED;
unsigned long lastPiMessage = 0;
bool piConnected = true;
bool scheduleComplete = false;

// Current Position
uint8_t currentAzimuth = PARK_AZ;
uint8_t currentElevation = PARK_EL;

// Schedule Storage
struct ScheduleEntry {
  uint16_t delayMinutes;   // Delay from schedule start in minutes
  uint8_t azimuth;
  uint8_t elevation;
};

ScheduleEntry schedule[48];
uint8_t scheduleCount = 0;
uint8_t currentScheduleIndex = 0;
unsigned long scheduleStartTime = 0;

// Timers
Timer movementTimer;
Timer gpsReadTimer;
Timer heartbeatTimer;

// GPS Reading Variables
String currentNmeaSentence = "";
bool waitingForAck = false;

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600);
  
  // Initialize servo driver
  pwm.begin();
  pwm.setPWMFreq(SERVO_FREQ);
  
  // Initialize timers
  heartbeatTimer.start(HEARTBEAT_INTERVAL);
  
  // Park motors on startup
  moveToPosition(PARK_AZ, PARK_EL);

  //prevent Heap Fragmentation
  currentNmeaSentence.reserve(100);
  
  Serial.println("INIT:OK");
}

void loop() {
  unsigned long currentMillis = millis();
  
  // 1. Check for Pi commands
  if (Serial.available()) {
    processCommand();
    lastPiMessage = currentMillis;
    piConnected = true;
  }
  
  // 2. Check watchdog (non-blocking)
  if (piConnected && (currentMillis - lastPiMessage > WATCHDOG_TIMEOUT)) {
    handleWatchdogTimeout();
  }
  
  // 3. Handle state machine
  handleStateMachine();
  
  // 4. Send heartbeat periodically
  if (heartbeatTimer.isDone()) {
    sendHeartbeat();
    heartbeatTimer.start(HEARTBEAT_INTERVAL);
  }
  
  // 5. Minimal delay for stability
  delay(10);
}

void processCommand() {
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  
  // Reset watchdog on any command
  lastPiMessage = millis();
  piConnected = true;
  
  if (cmd.startsWith("SET_TIME:")) {
    // Format: SET_TIME:unix_timestamp
    setScheduleStartTime(cmd.substring(9));
  }
  else if (cmd.startsWith("SCH:")) {
    // Format: SCH:index,delay_minutes,az,el
    parseSchedule(cmd.substring(4));
  }
  else if (cmd.startsWith("MOV:")) {
    // Format: MOV:az,el
    parseMove(cmd.substring(4));
  }
  else if (cmd == "GPS") {
    startGpsAcquisition();
  }
  else if (cmd == "START") {
    startTracking();
  }
  else if (cmd == "STOP") {
    stopTracking();
  }
  else if (cmd == "PARK") {
    parkMotors();
  }
  else if (cmd == "STAT") {
    sendStatus();
  }
  else if (cmd == "PING") {
    // Pi heartbeat - just reset watchdog
  }
  else if (cmd == "END") {
    endOfDay();
  }
  else if (cmd == "ACK") {
    handleAck();
  }
  else if (cmd == "SCHEDULE_END") {
    scheduleComplete = true;
    Serial.println("SCHEDULE:LOADED");
  }
  else if (cmd == "RESET") {
    resetWatchdog();
  }
}

void setScheduleStartTime(String timestampStr) {
  // Convert Unix timestamp to Arduino schedule start time
  // We use the timestamp to calculate delays, but Arduino only needs relative times
  unsigned long unixTime = timestampStr.toInt();
  scheduleStartTime = millis();
  
  Serial.print("TIME_SET:");
  Serial.println(unixTime);
}

void parseSchedule(String data) {
  // Format: index,delay_minutes,azimuth,elevation
  int comma1 = data.indexOf(',');
  int comma2 = data.indexOf(',', comma1 + 1);
  int comma3 = data.indexOf(',', comma2 + 1);
  
  if (comma1 > 0 && comma2 > 0 && comma3 > 0) {
    uint8_t index = data.substring(0, comma1).toInt();
    uint16_t delayMinutes = data.substring(comma1 + 1, comma2).toInt();
    uint8_t azimuth = data.substring(comma2 + 1, comma3).toInt();
    uint8_t elevation = data.substring(comma3 + 1).toInt();
    
    if (index < 48) {
      schedule[index].delayMinutes = delayMinutes;
      schedule[index].azimuth = azimuth;
      schedule[index].elevation = elevation;
      
      scheduleCount = max(scheduleCount, (uint8_t)(index + 1));
    }
  }
}

void parseMove(String data) {
  int comma = data.indexOf(',');
  if (comma > 0) {
    uint8_t az = data.substring(0, comma).toInt();
    uint8_t el = data.substring(comma + 1).toInt();
    moveToPosition(az, el);
  }
}

void moveToPosition(uint8_t azimuth, uint8_t elevation) {
  // Apply limits
  azimuth = constrain(azimuth, AZ_MIN, AZ_MAX);
  elevation = constrain(elevation, EL_MIN, EL_MAX);
  
  // Convert to PWM
  int azPulse = map(azimuth, 0, 180, SERVOMIN, SERVOMAX);
  int elPulse = map(elevation, 0, 180, SERVOMIN, SERVOMAX);
  
  // Start movement
  pwm.setPWM(0, 0, azPulse);
  pwm.setPWM(1, 0, elPulse);
  
  // Start non-blocking timer for movement
  movementTimer.start(MOVEMENT_TIMEOUT);
  
  // Update state
  currentState = STATE_MOVING;
  currentAzimuth = azimuth;
  currentElevation = elevation;
  
  Serial.print("MOVING:");
  Serial.print(azimuth);
  Serial.print(",");
  Serial.println(elevation);
}

void parkMotors() {
  moveToPosition(PARK_AZ, PARK_EL);
  currentState = STATE_PARKED;
  scheduleCount = 0;
  currentScheduleIndex = 0;
  scheduleComplete = false;
  
  Serial.println("PARKED");
}

void startGpsAcquisition() {
  Serial.println("GPS:STARTING");
  currentState = STATE_GETTING_GPS;
  waitingForAck = false;
  currentNmeaSentence = "";
  
  // Clear GPS buffer
  while (gpsSerial.available()) {
    gpsSerial.read();
  }
  
  // Start GPS read timer
  gpsReadTimer.start(GPS_READ_TIMEOUT);
}

void startTracking() {
  if (scheduleCount == 0) {
    Serial.println("ERR:NO_SCHEDULE");
    return;
  }
  
  currentState = STATE_TRACKING;
  currentScheduleIndex = 0;
  scheduleComplete = false;
  
  Serial.println("TRACKING:STARTED");
}

void stopTracking() {
  currentState = STATE_IDLE;
  Serial.println("TRACKING:STOPPED");
}

void endOfDay() {
  parkMotors();
  Serial.println("END_OF_DAY");
}

void handleStateMachine() {
  switch (currentState) {
    case STATE_IDLE:
      // Do nothing, waiting for commands
      break;
      
    case STATE_TRACKING:
      handleTracking();
      break;
      
    case STATE_WATCHDOG:
      handleWatchdogState();
      break;
      
    case STATE_PARKED:
      // Motors parked, minimal operation
      break;
      
    case STATE_GETTING_GPS:
      handleGpsAcquisition();
      break;
      
    case STATE_MOVING:
      handleMovement();
      break;
      
    case STATE_WAITING_FOR_ACK:
      // Waiting for ACK from Pi - will be handled in processCommand
      break;
  }
}

void handleTracking() {
  if (currentScheduleIndex >= scheduleCount) {
    // Schedule complete
    Serial.println("TRACKING:COMPLETE");
    endOfDay();
    return;
  }
  
  // Check if it's time to move to next position
  unsigned long currentMinutes = (millis() - scheduleStartTime) / 60000;
  ScheduleEntry next = schedule[currentScheduleIndex];
  
  if (currentMinutes >= next.delayMinutes) {
    // Time to move
    moveToPosition(next.azimuth, next.elevation);
    currentScheduleIndex++;
    
    // Notify Pi
    Serial.print("TRACKING:MOVED_TO_");
    Serial.println(currentScheduleIndex - 1);
  }
}

void handleGpsAcquisition() {
  // Read GPS data non-blockingly
  while (gpsSerial.available() && !waitingForAck) {
    char c = gpsSerial.read();
    
    // Check for end of NMEA sentence
    if (c == '\n') {
      // Complete NMEA sentence received
      if (currentNmeaSentence.startsWith("$GPGGA") || 
          currentNmeaSentence.startsWith("$GPRMC")) {
        
        // Send to Pi
        Serial.print("GPS_RAW:");
        Serial.println(currentNmeaSentence);
        
        // Wait for ACK
        waitingForAck = true;
        currentState = STATE_WAITING_FOR_ACK;
        
        // Reset sentence buffer
        currentNmeaSentence = "";
        return;
      }
      currentNmeaSentence = "";
    } 
    else if (c == '\r') {
      // Ignore carriage return
    } 
    else if (currentNmeaSentence.length() < 100) {
      // Add to buffer, limit length
      currentNmeaSentence += c;
    }
  }
  
  // Check timeout
  if (gpsReadTimer.isDone() && !waitingForAck) {
    Serial.println("GPS:TIMEOUT");
    currentState = STATE_IDLE;
    currentNmeaSentence = "";
  }
}

void handleMovement() {
  // Check if movement is complete (non-blocking)
  if (movementTimer.isDone()) {
    // Movement complete
    Serial.print("MOVED:");
    Serial.print(currentAzimuth);
    Serial.print(",");
    Serial.println(currentElevation);
    currentState = STATE_TRACKING;
  }
  
  // Still allow processing commands during movement
  // (Arduino can handle servo PWM and serial communication simultaneously)
}

void handleAck() {
  if (waitingForAck) {
    waitingForAck = false;
    
    if (currentState == STATE_WAITING_FOR_ACK) {
      currentState = STATE_IDLE;
      Serial.println("GPS:ACK_RECEIVED");
    }
  }
}

void handleWatchdogTimeout() {
  Serial.println("WATCHDOG:TIMEOUT");
  piConnected = false;
  
  // Emergency actions
  if (currentState == STATE_TRACKING || 
      currentState == STATE_MOVING || 
      currentState == STATE_GETTING_GPS) {
    parkMotors();
    currentState = STATE_WATCHDOG;
  }
}

void handleWatchdogState() {
  // Blink built-in LED to indicate watchdog state
  static unsigned long lastBlink = 0;
  static bool ledState = false;
  
  if (millis() - lastBlink > 500) {
    digitalWrite(13, ledState ? HIGH : LOW);
    ledState = !ledState;
    lastBlink = millis();
  }
  
  // Check for reset command (handled in processCommand)
}

void resetWatchdog() {
  piConnected = true;
  lastPiMessage = millis();
  digitalWrite(13, LOW);
  
  if (currentState == STATE_WATCHDOG) {
    currentState = STATE_IDLE;
    Serial.println("WATCHDOG:RESET");
  }
}

void sendHeartbeat() {
  // Only send heartbeat if Pi is connected
  if (piConnected) {
    Serial.println("HB");
  }
}

void sendStatus() {
  Serial.print("STAT:");
  Serial.print(currentState);
  Serial.print(",");
  Serial.print(currentAzimuth);
  Serial.print(",");
  Serial.print(currentElevation);
  Serial.print(",");
  Serial.print(scheduleCount);
  Serial.print(",");
  Serial.print(currentScheduleIndex);
  Serial.print(",");
  Serial.print(scheduleComplete ? "1" : "0");
  Serial.print(",");
  Serial.print(piConnected ? "1" : "0");
  Serial.print(",");
  Serial.print(millis() - lastPiMessage);
  Serial.println();
}
