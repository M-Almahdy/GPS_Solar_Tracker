#!/bin/bash
# Solar Tracker Installation Script for Raspberry Pi
# Usage: sudo bash setup.sh

set -e  # Exit on error

echo "========================================="
echo "  Solar Tracker Installation Script"
echo "========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Update system
echo "[1/10] Updating system packages..."
apt update
apt upgrade -y

# Install system dependencies
echo "[2/10] Installing system dependencies..."
apt install -y \
    python3-pip \
    python3-dev \
    python3-serial \
    python3-setuptools \
    i2c-tools \
    git \
    screen \
    tmux \
    ntp \
    ntpdate \
    gpsd \
    gpsd-clients \
    minicom \
    pigpio \
    python3-pigpio \
    python3-flask \
    python3-geopy \
    python3-schedule

# Enable required interfaces
echo "[3/10] Enabling hardware interfaces..."

# Enable I2C
raspi-config nonint do_i2c 0

# Enable UART for Arduino communication
raspi-config nonint do_serial 2

# Remove console from serial
sed -i 's/console=serial0,115200 //' /boot/cmdline.txt

# Add UART configuration to config.txt
if ! grep -q "enable_uart=1" /boot/config.txt; then
    echo "enable_uart=1" >> /boot/config.txt
fi

# Set core frequency for stable UART
if ! grep -q "core_freq=250" /boot/config.txt; then
    echo "core_freq=250" >> /boot/config.txt
fi

# Configure GPSD
echo "[4/10] Configuring GPSD..."
systemctl stop gpsd.socket
systemctl disable gpsd.socket

# Create GPSD configuration
cat > /etc/default/gpsd << EOF
# Default settings for the gpsd init script and the hotplug wrapper.
# Start the gpsd daemon automatically at boot time
START_DAEMON="true"
# Use USB hotplugging to add new USB devices automatically to the daemon
USBAUTO="true"
# Devices gpsd should collect to at boot time.
# They need to be read/writeable, either by user gpsd or the group dialout.
DEVICES="/dev/ttyAMA0"
# Other options you want to pass to gpsd
GPSD_OPTIONS="-n"
EOF

# Create udev rule for Arduino
echo "[5/10] Creating udev rules..."
cat > /etc/udev/rules.d/99-arduino.rules << EOF
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0043", SYMLINK+="arduino_uno"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0001", SYMLINK+="arduino_uno"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2a03", ATTRS{idProduct}=="0043", SYMLINK+="arduino_uno"
KERNEL=="ttyACM*", SYMLINK+="arduino"
EOF

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

# Install Python packages
echo "[6/10] Installing Python packages..."
pip3 install \
    pyserial \
    schedule \
    geopy \
    flask \
    flask-cors \
    python-dateutil \
    psutil \
    Adafruit-PCA9685 \
    Adafruit-GPIO

# Set timezone to UTC (recommended for solar calculations)
echo "[7/10] Setting timezone to UTC..."
timedatectl set-timezone UTC

# Enable NTP for accurate time
systemctl enable systemd-timesyncd
systemctl start systemd-timesyncd

# Create solar-tracker user (optional)
echo "[8/10] Setting up user and permissions..."
useradd -r -s /bin/false solar-tracker 2>/dev/null || true
usermod -a -G dialout pi
usermod -a -G dialout solar-tracker 2>/dev/null || true

# Create log directory with correct permissions
mkdir -p /var/log/solar-tracker
chown pi:pi /var/log/solar-tracker
chmod 755 /var/log/solar-tracker

# Create systemd service
echo "[9/10] Creating systemd service..."
cat > /etc/systemd/system/solar-tracker.service << EOF
[Unit]
Description=Solar Tracker Service
After=network.target gpsd.service
Wants=gpsd.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solar-tracker
ExecStart=/usr/bin/python3 /home/pi/solar-tracker/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/pi/solar-tracker /tmp

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl enable solar-tracker.service

# Create web server service
cat > /etc/systemd/system/solar-tracker-web.service << EOF
[Unit]
Description=Solar Tracker Web Interface
After=network.target solar-tracker.service
Wants=solar-tracker.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solar-tracker
ExecStart=/usr/bin/python3 /home/pi/solar-tracker/web_server.py
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl enable solar-tracker-web.service

echo "[10/10] Finalizing installation..."
# Set execute permissions
chmod +x /home/pi/solar-tracker/*.py

echo ""
echo "========================================="
echo "  Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration:"
echo "   nano /home/pi/solar-tracker/config.json"
echo ""
echo "2. Set your location in config.json:"
echo "   - latitude"
echo "   - longitude"
echo "   - timezone"
echo ""
echo "3. Upload Arduino code to Arduino Uno"
echo ""
echo "4. Start the services:"
echo "   sudo systemctl start solar-tracker"
echo "   sudo systemctl start solar-tracker-web"
echo ""
echo "5. Access web interface at:"
echo "   http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "6. Check logs:"
echo "   sudo journalctl -u solar-tracker -f"
echo ""
echo "========================================="