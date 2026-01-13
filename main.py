#!/usr/bin/env python3
"""
Solar Tracker Main Controller
Raspberry Pi side of the system
"""
import os
import sys
import time
import json
import logging
import threading
import schedule
from datetime import datetime, timedelta

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import local modules
from solar_calculator import SolarCalculator
from arduino_controller import ArduinoController
from web_server import WebServer
from power_manager import PowerManager

# Configure logging
def setup_logging():
    """Configure logging system"""
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, 'tracker.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

class SolarTracker:
    def __init__(self):
        """Initialize solar tracker system"""
        self.logger = setup_logging()
        self.logger.info("Initializing Solar Tracker System")
        
        # Load configuration
        self.config = self.load_config()
        
        # Initialize components
        self.solar_calc = SolarCalculator()
        self.arduino = ArduinoController(self.config)
        self.power_mgr = PowerManager(self.config)
        
        # System state
        self.tracking_active = False
        self.schedule_loaded = False
        self.current_schedule = []
        self.current_day = None
        
        # Threading
        self.stop_event = threading.Event()
        self.monitor_thread = None
        
        # Setup signal handlers
        self.setup_signal_handlers()
        
        self.logger.info("Solar Tracker initialized")
    
    def load_config(self):
        """Load configuration from file"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Set defaults if missing
            defaults = {
                'location': {'latitude': 0.0, 'longitude': 0.0, 'timezone': 'UTC'},
                'tracking': {'interval_minutes': 30, 'park_at_night': True},
                'web_server': {'port': 8080, 'enabled': True}
            }
            
            # Merge defaults
            for section, values in defaults.items():
                if section not in config:
                    config[section] = values
                else:
                    for key, value in values.items():
                        if key not in config[section]:
                            config[section][key] = value
            
            return config
            
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            # Return minimal config
            return defaults
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        import signal
        
        def signal_handler(sig, frame):
            self.logger.info(f"Received signal {sig}, shutting down...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def startup_sequence(self):
        """System startup sequence"""
        self.logger.info("Starting system startup sequence")
        
        # 1. Connect to Arduino
        if not self.arduino.connect():
            self.logger.error("Failed to connect to Arduino")
            return False
        
        # 2. Get GPS location
        if not self.get_gps_location():
            self.logger.warning("Could not get GPS location, using configured location")
        
        # 3. Check if it's daytime
        if self.is_daytime():
            self.logger.info("Daytime detected - starting tracking")
            self.start_tracking()
        else:
            self.logger.info("Nighttime detected - scheduling morning start")
            self.schedule_morning_start()
        
        # 4. Start web server if enabled
        if self.config['web_server']['enabled']:
            self.start_web_server()
        
        # 5. Start monitoring thread
        self.start_monitoring()
        
        return True
    
    def get_gps_location(self):
        """Get current location via GPS"""
        self.logger.info("Acquiring GPS location...")
        
        try:
            location = self.arduino.get_gps_location(timeout=60)
            
            if location:
                # Update configuration
                self.config['location']['latitude'] = location['latitude']
                self.config['location']['longitude'] = location['longitude']
                self.config['location']['altitude'] = location.get('altitude', 0)
                
                # Save updated config
                self.save_config()
                
                self.logger.info(f"GPS location acquired: {location['latitude']}, {location['longitude']}")
                return True
        
        except Exception as e:
            self.logger.error(f"GPS acquisition failed: {e}")
        
        return False
    
    def is_daytime(self):
        """Check if it's currently daytime"""
        now = datetime.now()
        
        # Simple check (6 AM to 6 PM)
        if 6 <= now.hour < 18:
            return True
        
        # More accurate check using solar calculator
        sunrise, sunset = self.solar_calc.get_sunrise_sunset(
            self.config['location']['latitude'],
            self.config['location']['longitude']
        )
        
        if sunrise and sunset:
            now_time = now.time()
            return sunrise <= now_time <= sunset
        
        return False
    
    def calculate_daily_schedule(self):
        """Calculate solar positions for today"""
        day_of_year = datetime.now().timetuple().tm_yday
        
        # Don't recalculate if already done today
        if day_of_year == self.current_day and self.schedule_loaded:
            self.logger.info("Using existing schedule for today")
            return True
        
        self.logger.info(f"Calculating schedule for day {day_of_year}")
        
        # Get sunrise and sunset
        sunrise, sunset = self.solar_calc.get_sunrise_sunset(
            self.config['location']['latitude'],
            self.config['location']['longitude']
        )
        
        if not sunrise or not sunset:
            self.logger.error("Could not calculate sunrise/sunset")
            return False
        
        # Calculate positions every X minutes
        interval = self.config['tracking']['interval_minutes']
        positions = []
        
        current = datetime.combine(datetime.now().date(), sunrise)
        end = datetime.combine(datetime.now().date(), sunset)
        
        # Add offset from sunrise
        sunrise_offset = self.config['tracking'].get('sunrise_offset', 30)
        current += timedelta(minutes=sunrise_offset)
        
        index = 0
        while current <= end:
            # Calculate solar position
            azimuth, elevation = self.solar_calc.calculate_position(
                current,
                self.config['location']['latitude'],
                self.config['location']['longitude']
            )
            
            if azimuth is not None and elevation is not None:
                # Calculate delay from now in minutes
                delay = int((current - datetime.now()).total_seconds() / 60)
                
                # Only include future positions
                if delay >= 0:
                    position = {
                        'index': index,
                        'time': current.time(),
                        'delay_minutes': delay,
                        'azimuth': azimuth,
                        'elevation': elevation,
                        'timestamp': current.timestamp()
                    }
                    
                    positions.append(position)
                    index += 1
            
            current += timedelta(minutes=interval)
        
        self.current_schedule = positions
        self.current_day = day_of_year
        self.schedule_loaded = True
        
        # Send schedule to Arduino
        self.send_schedule_to_arduino()
        
        self.logger.info(f"Calculated {len(positions)} positions for today")
        return True
    
    def send_schedule_to_arduino(self):
        """Send schedule to Arduino"""
        if not self.current_schedule:
            self.logger.error("No schedule to send")
            return False
        
        self.logger.info(f"Sending {len(self.current_schedule)} positions to Arduino")
        
        # Set current time on Arduino
        unix_time = int(time.time())
        self.arduino.send_command(f"SET_TIME:{unix_time}")
        
        # Send each position
        for position in self.current_schedule:
            cmd = f"SCH:{position['index']},{position['delay_minutes']},{int(position['azimuth'])},{int(position['elevation'])}"
            self.arduino.send_command(cmd)
            time.sleep(0.01)  # Small delay
        
        # Mark end of schedule
        self.arduino.send_command("SCHEDULE_END")
        
        self.logger.info("Schedule sent to Arduino")
        return True
    
    def start_tracking(self):
        """Start solar tracking"""
        if not self.schedule_loaded:
            if not self.calculate_daily_schedule():
                self.logger.error("Failed to calculate schedule")
                return False
        
        self.logger.info("Starting solar tracking")
        
        if self.arduino.send_command("START"):
            self.tracking_active = True
            
            # Schedule end of day
            self.schedule_end_of_day()
            
            self.logger.info("Solar tracking started")
            return True
        
        return False
    
    def schedule_end_of_day(self):
        """Schedule end-of-day parking"""
        sunrise, sunset = self.solar_calc.get_sunrise_sunset(
            self.config['location']['latitude'],
            self.config['location']['longitude']
        )
        
        if sunset:
            # Park X minutes before sunset
            sunset_offset = self.config['tracking'].get('sunset_offset', 30)
            park_time = (datetime.combine(datetime.now().date(), sunset) - 
                        timedelta(minutes=sunset_offset)).time()
            
            schedule.every().day.at(park_time.strftime("%H:%M")).do(
                self.end_of_day
            )
            
            self.logger.info(f"End-of-day scheduled for {park_time}")
    
    def end_of_day(self):
        """End of day routine"""
        self.logger.info("End of day - parking system")
        
        self.arduino.send_command("END")
        self.tracking_active = False
        
        # Clear schedule
        schedule.clear()
        
        # Schedule morning start
        self.schedule_morning_start()
        
        self.logger.info("System parked for night")
    
    def schedule_morning_start(self):
        """Schedule system start in the morning"""
        # Schedule for 30 minutes before sunrise
        sunrise, _ = self.solar_calc.get_sunrise_sunset(
            self.config['location']['latitude'],
            self.config['location']['longitude']
        )
        
        if sunrise:
            start_time = (datetime.combine(datetime.now().date() + timedelta(days=1), sunrise) - 
                         timedelta(minutes=30)).time()
            
            schedule.every().day.at(start_time.strftime("%H:%M")).do(
                self.morning_startup
            )
            
            self.logger.info(f"Morning start scheduled for {start_time}")
        else:
            # Fallback to 6 AM
            schedule.every().day.at("06:00").do(self.morning_startup)
            self.logger.info("Morning start scheduled for 06:00")
    
    def morning_startup(self):
        """Morning startup routine"""
        self.logger.info("Morning startup sequence")
        
        # Get fresh GPS location
        if not self.get_gps_location():
            self.logger.warning("Using last known GPS location")
        
        # Calculate new schedule
        self.schedule_loaded = False
        if self.calculate_daily_schedule():
            # Start tracking
            self.start_tracking()
        else:
            self.logger.error("Failed to calculate schedule")
    
    def start_web_server(self):
        """Start web interface server"""
        try:
            web_server = WebServer(self.config)
            web_thread = threading.Thread(target=web_server.run, daemon=True)
            web_thread.start()
            self.logger.info(f"Web server started on port {self.config['web_server']['port']}")
        except Exception as e:
            self.logger.error(f"Failed to start web server: {e}")
    
    def start_monitoring(self):
        """Start system monitoring thread"""
        def monitor():
            while not self.stop_event.is_set():
                try:
                    # Check Arduino status
                    status = self.arduino.get_status()
                    if status:
                        self.update_system_status(status)
                    
                    # Check power status
                    power_status = self.power_mgr.get_status()
                    
                    # Log system health
                    self.logger.debug(f"System status: {status}")
                    
                    # Sleep
                    time.sleep(30)
                    
                except Exception as e:
                    self.logger.error(f"Monitor error: {e}")
                    time.sleep(60)
        
        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()
        self.logger.info("System monitoring started")
    
    def update_system_status(self, status):
        """Update system status file"""
        status_file = os.path.join(os.path.dirname(__file__), 'data', 'system_status.json')
        
        try:
            os.makedirs(os.path.dirname(status_file), exist_ok=True)
            
            status_data = {
                **status,
                'tracking_active': self.tracking_active,
                'schedule_loaded': self.schedule_loaded,
                'current_day': self.current_day,
                'position_count': len(self.current_schedule),
                'timestamp': datetime.now().isoformat()
            }
            
            with open(status_file, 'w') as f:
                json.dump(status_data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Failed to update status file: {e}")
    
    def save_config(self):
        """Save configuration to file"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.logger.debug("Configuration saved")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
    
    def shutdown(self):
        """Graceful system shutdown"""
        self.logger.info("Initiating shutdown sequence")
        
        # Stop monitoring
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        # Stop tracking
        if self.tracking_active:
            self.arduino.send_command("STOP")
        
        # Park motors
        self.arduino.send_command("PARK")
        time.sleep(3)
        
        # Disconnect Arduino
        self.arduino.disconnect()
        
        self.logger.info("Shutdown complete")
    
    def run(self):
        """Main run loop"""
        self.logger.info("Solar Tracker starting...")
        
        # Run startup sequence
        if not self.startup_sequence():
            self.logger.error("Startup sequence failed")
            return
        
        # Main loop
        try:
            while not self.stop_event.is_set():
                # Run scheduled tasks
                schedule.run_pending()
                
                # Send heartbeat to Arduino
                self.arduino.send_command("PING")
                
                # Small sleep
                time.sleep(1)
                
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Main loop error: {e}")
        finally:
            self.shutdown()

if __name__ == "__main__":
    tracker = SolarTracker()
    tracker.run()