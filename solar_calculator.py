#!/usr/bin/env python3
"""
Solar position calculator
"""
import math
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SolarCalculator:
    def __init__(self):
        pass
    
    def calculate_position(self, dt, latitude, longitude):
        """Calculate solar azimuth and elevation for given time and location"""
        try:
            # Convert to radians
            lat_rad = math.radians(latitude)
            
            # Day of year (1-365)
            day_of_year = dt.timetuple().tm_yday
            
            # Fractional year in radians
            gamma = 2 * math.pi / 365 * (day_of_year - 1)
            
            # Equation of time (minutes)
            eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) 
                              - 0.032077 * math.sin(gamma) 
                              - 0.014615 * math.cos(2 * gamma) 
                              - 0.040849 * math.sin(2 * gamma))
            
            # Solar declination (radians)
            decl = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) \
                   - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma) \
                   - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
            
            # Time offset (minutes)
            time_offset = eqtime + 4 * longitude - 60 * dt.utcoffset().total_seconds() / 3600 if dt.utcoffset() else eqtime + 4 * longitude
            
            # True solar time (minutes)
            tst = dt.hour * 60 + dt.minute + dt.second / 60 + time_offset
            
            # Hour angle (degrees)
            hour_angle = (tst / 4) - 180
            
            # Solar elevation (altitude)
            ha_rad = math.radians(hour_angle)
            sin_elevation = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(decl) * math.cos(ha_rad)
            sin_elevation = max(-1, min(1, sin_elevation))  # Clamp
            elevation = math.degrees(math.asin(sin_elevation))
            
            # Solar azimuth
            cos_azimuth = (math.sin(decl) * math.cos(lat_rad) - 
                          math.cos(decl) * math.sin(lat_rad) * math.cos(ha_rad)) / math.cos(math.radians(elevation))
            cos_azimuth = max(-1, min(1, cos_azimuth))  # Clamp
            azimuth = math.degrees(math.acos(cos_azimuth))
            
            # Adjust azimuth based on time of day
            if hour_angle > 0:
                azimuth = 360 - azimuth
            
            return azimuth, elevation
            
        except Exception as e:
            logger.error(f"Solar calculation error: {e}")
            return None, None
    
    def get_sunrise_sunset(self, latitude, longitude):
        """Calculate sunrise and sunset times for today"""
        try:
            # Get today's date
            today = datetime.now().date()
            noon = datetime.combine(today, datetime.strptime("12:00", "%H:%M").time())
            
            # Calculate declination for today
            day_of_year = noon.timetuple().tm_yday
            gamma = 2 * math.pi / 365 * (day_of_year - 1)
            decl = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            
            # Convert latitude to radians
            lat_rad = math.radians(latitude)
            
            # Hour angle for sunrise/sunset (when elevation = 0)
            cos_ha = -math.tan(lat_rad) * math.tan(decl)
            cos_ha = max(-1, min(1, cos_ha))  # Clamp
            
            ha = math.degrees(math.acos(cos_ha))
            
            # Sunrise/sunset in minutes from solar noon
            sunrise_offset = -ha * 4  # 4 minutes per degree
            sunset_offset = ha * 4
            
            # Convert to datetime
            sunrise = noon + timedelta(minutes=sunrise_offset)
            sunset = noon + timedelta(minutes=sunset_offset)
            
            return sunrise.time(), sunset.time()
            
        except Exception as e:
            logger.error(f"Sunrise/sunset calculation error: {e}")
            return None, None