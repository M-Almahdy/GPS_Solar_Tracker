#!/bin/bash
# Uninstall Solar Tracker
echo "Uninstalling Solar Tracker..."

# Stop services
sudo systemctl stop solar-tracker.service
sudo systemctl stop solar-tracker-web.service

# Disable services
sudo systemctl disable solar-tracker.service
sudo systemctl disable solar-tracker-web.service

# Remove services
sudo rm -f /etc/systemd/system/solar-tracker.service
sudo rm -f /etc/systemd/system/solar-tracker-web.service

# Reload systemd
sudo systemctl daemon-reload

# Remove udev rules
sudo rm -f /etc/udev/rules.d/99-arduino.rules

# Reload udev
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "Uninstallation complete."
echo "Note: Configuration and data files in /home/pi/solar-tracker were not removed."