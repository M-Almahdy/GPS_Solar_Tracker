#!/usr/bin/env python3
"""
Power management for solar-powered system
"""
import logging

logger = logging.getLogger(__name__)

class PowerManager:
    def __init__(self, config):
        self.config = config
        
        # Power settings
        self.battery_voltage = 12.0
        self.solar_voltage = 0.0
        self.load_current = 0.0
        
        logger.info("Power Manager initialized")
    
    def get_status(self):
        """Get power status"""
        # This would read from ADC or I2C power monitor
        # For now, return simulated data
        return {
            'battery_voltage': self.battery_voltage,
            'solar_voltage': self.solar_voltage,
            'load_current': self.load_current,
            'power_source': self.config['power']['source'],
            'battery_percentage': self._calculate_battery_percentage()
        }
    
    def _calculate_battery_percentage(self):
        """Calculate battery percentage based on voltage"""
        voltage = self.battery_voltage
        
        # Simple calculation for 12V LiFePO4
        if voltage >= 13.6:
            return 100
        elif voltage >= 13.2:
            return 75
        elif voltage >= 12.8:
            return 50
        elif voltage >= 12.0:
            return 25
        else:
            return 0
    
    def check_battery(self):
        """Check battery status and take action if needed"""
        low_voltage = self.config['power']['low_voltage_threshold']
        critical_voltage = self.config['power']['critical_voltage_threshold']
        
        if self.battery_voltage <= critical_voltage:
            logger.critical(f"Battery critical: {self.battery_voltage}V")
            return 'critical'
        elif self.battery_voltage <= low_voltage:
            logger.warning(f"Battery low: {self.battery_voltage}V")
            return 'low'
        
        return 'ok'