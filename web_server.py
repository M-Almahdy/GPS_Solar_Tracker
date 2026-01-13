#!/usr/bin/env python3
"""
Web interface for solar tracker
"""
from flask import Flask, render_template, jsonify, request
import json
import os
import threading
from datetime import datetime

class WebServer:
    def __init__(self, config):
        self.config = config
        self.app = Flask(__name__, 
                        static_folder='web/static',
                        template_folder='web/templates')
        self.setup_routes()
        
        # Web server settings
        self.host = '0.0.0.0'
        self.port = config['web_server']['port']
        self.debug = False
        
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/status')
        def api_status():
            try:
                status_file = os.path.join(os.path.dirname(__file__), 'data', 'system_status.json')
                with open(status_file, 'r') as f:
                    status = json.load(f)
                return jsonify(status)
            except:
                return jsonify({'error': 'No status available'})
        
        @self.app.route('/api/config')
        def api_config():
            return jsonify(self.config)
        
        @self.app.route('/api/control/<command>')
        def api_control(command):
            # This would interface with the main controller
            # For now, just return success
            return jsonify({'success': True, 'command': command})
        
        @self.app.route('/api/logs')
        def api_logs():
            try:
                log_file = os.path.join(os.path.dirname(__file__), 'logs', 'tracker.log')
                with open(log_file, 'r') as f:
                    logs = f.read().split('\n')[-100:]  # Last 100 lines
                return jsonify({'logs': logs})
            except:
                return jsonify({'logs': []})
    
    def run(self):
        """Run web server"""
        self.app.run(host=self.host, port=self.port, debug=self.debug, threaded=True)