import json
from pathlib import Path
from flask import Flask, send_from_directory, jsonify
import sys

# Ensure config is accessible
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def create_app():
    app = Flask(__name__, static_folder=".", static_url_path="")

    @app.route("/")
    def index():
        return send_from_directory(".", "index.html")

    @app.route("/data/<filename>")
    def get_data(filename):
        data_dir = Path(config.DATA_DIR)
        file_path = data_dir / filename
        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=True)
