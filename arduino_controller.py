#!/usr/bin/env python3
"""
Arduino communication controller
"""
import serial
import time
import logging
import threading

logger = logging.getLogger(__name__)

class ArduinoController:
    def __init__(self, config):
        self.config = config
        self.serial = None
        self.connected = False
        self.lock = threading.Lock()
        
        # Arduino settings
        self.port = config['hardware']['arduino']['port']
        self.baudrate = config['hardware']['arduino']['baudrate']
        
        # Communication timeout
        self.timeout = 2
    
    def connect(self):
        """Connect to Arduino"""
        try:
            with self.lock:
                self.serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout
                )
                
                # Wait for Arduino to initialize
                time.sleep(2)
                
                # Clear buffer
                self.serial.reset_input_buffer()
                self.serial.reset_output_buffer()
                
                # Test connection
                response = self._send_command("PING", timeout=3)
                if response and "PONG" in response:
                    self.connected = True
                    logger.info(f"Connected to Arduino on {self.port}")
                    return True
        
        except Exception as e:
            logger.error(f"Failed to connect to Arduino: {e}")
        
        return False
    
    def send_command(self, command):
        """Send command to Arduino"""
        if not self.connected:
            logger.error("Arduino not connected")
            return False
        
        try:
            response = self._send_command(command)
            return response is not None
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            self.connected = False
            return False
    
    def _send_command(self, command, timeout=None):
        """Internal method to send command and wait for response"""
        with self.lock:
            if not self.serial or not self.serial.is_open:
                return None
            
            # Send command
            self.serial.write(f"{command}\n".encode())
            self.serial.flush()
            
            # Read response
            timeout = timeout or self.timeout
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if self.serial.in_waiting > 0:
                    try:
                        line = self.serial.readline().decode().strip()
                        logger.debug(f"Arduino: {line}")
                        return line
                    except Exception as e:
                        logger.error(f"Read error: {e}")
                        break
            
            return None
    
    def get_gps_location(self, timeout=60):
        """Get GPS location from Arduino"""
        logger.info("Requesting GPS location from Arduino...")
        
        # Start GPS acquisition
        response = self._send_command("GPS", timeout=5)
        if not response or "GPS:STARTING" not in response:
            logger.error("Failed to start GPS acquisition")
            return None
        
        # Wait for GPS data
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.serial.in_waiting > 0:
                try:
                    line = self.serial.readline().decode().strip()
                    
                    if line.startswith("GPS_RAW:"):
                        # Parse NMEA sentence
                        nmea = line[8:]
                        
                        # Send ACK
                        self._send_command("ACK")
                        
                        # Parse GPS data
                        location = self._parse_nmea(nmea)
                        if location:
                            return location
                    
                    elif "GPS:TIMEOUT" in line:
                        logger.warning("GPS acquisition timeout")
                        break
                        
                except Exception as e:
                    logger.error(f"GPS read error: {e}")
            
            time.sleep(0.1)
        
        return None
    
    def _parse_nmea(self, nmea_sentence):
        """Parse NMEA sentence to extract location"""
        try:
            # Simple GGA parser
            if nmea_sentence.startswith("$GPGGA"):
                parts = nmea_sentence.split(',')
                
                if len(parts) >= 10 and parts[6] != '0':  # Fix quality > 0
                    # Parse latitude
                    lat_str = parts[2]
                    lat_dir = parts[3]
                    latitude = self._nmea_to_decimal(lat_str, lat_dir)
                    
                    # Parse longitude
                    lon_str = parts[4]
                    lon_dir = parts[5]
                    longitude = self._nmea_to_decimal(lon_str, lon_dir)
                    
                    # Parse altitude
                    altitude = float(parts[9]) if parts[9] else 0
                    
                    # Parse satellites
                    satellites = int(parts[7]) if parts[7] else 0
                    
                    # Parse HDOP
                    hdop = float(parts[8]) if parts[8] else 0
                    
                    return {
                        'latitude': latitude,
                        'longitude': longitude,
                        'altitude': altitude,
                        'satellites': satellites,
                        'hdop': hdop,
                        'timestamp': time.time()
                    }
        
        except Exception as e:
            logger.error(f"NMEA parse error: {e}")
        
        return None
    
    def _nmea_to_decimal(self, nmea_coord, direction):
        """Convert NMEA coordinate to decimal degrees"""
        try:
            # Format: DDMM.MMMM
            dot_pos = nmea_coord.find('.')
            if dot_pos < 2:
                return 0.0
            
            degrees = float(nmea_coord[:dot_pos-2])
            minutes = float(nmea_coord[dot_pos-2:])
            
            decimal = degrees + (minutes / 60.0)
            
            # Apply direction
            if direction in ['S', 'W']:
                decimal = -decimal
            
            return round(decimal, 6)
        except:
            return 0.0
    
    def get_status(self):
        """Get status from Arduino"""
        response = self._send_command("STAT", timeout=3)
        
        if response and response.startswith("STAT:"):
            try:
                parts = response[5:].split(',')
                if len(parts) >= 8:
                    return {
                        'state': int(parts[0]),
                        'azimuth': int(parts[1]),
                        'elevation': int(parts[2]),
                        'schedule_count': int(parts[3]),
                        'schedule_index': int(parts[4]),
                        'schedule_complete': parts[5] == "1",
                        'pi_connected': parts[6] == "1",
                        'last_msg_age': int(parts[7])
                    }
            except Exception as e:
                logger.error(f"Status parse error: {e}")
        
        return None
    
    def disconnect(self):
        """Disconnect from Arduino"""
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False
        logger.info("Disconnected from Arduino")