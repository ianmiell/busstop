"""
Realtime London bus stop info via TFL.
https://github.com/soinkleined/busstop
"""

import configparser
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from flask import Flask, abort, jsonify, make_response, redirect, request, render_template, url_for
from turbo_flask import Turbo
from tfl_bus_monitor.tfl_bus_monitor import TFLBusMonitor, get_config_path

UPDATE_INTERVAL = 15

app = Flask(__name__)
turbo = Turbo(app)
monitor = TFLBusMonitor()

# Global cache for stop data. "profiles" maps profile name -> list of stop data.
latest_data = {
    "all_stops": [],
    "profiles": {},
}

PROFILE_COOKIE = "profile"
PROFILES_FILE_NAME = "busstop_profiles.json"
DEFAULT_PROFILE_NAME = "Ian home"
STOP_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
MAX_PROFILE_NAME_LEN = 40
profiles_lock = threading.RLock()


def profiles_path():
    """Profiles live next to the ini config file and are managed in the UI."""
    return Path(get_config_path()).parent / PROFILES_FILE_NAME


def _default_profiles():
    """Seed profiles from the existing ini config so nothing is lost."""
    stops = []
    try:
        cfg = configparser.ConfigParser()
        cfg.read(get_config_path())
        ids = [i.strip() for i in cfg.get("busstop", "stopid").split(",") if i.strip()]
        nums = [n.strip() for n in cfg.get("busstop", "num_services").split(",") if n.strip()]
        for stop_id, num in zip(ids, nums):
            stops.append({"stopid": stop_id, "num_services": int(num)})
    except (configparser.Error, ValueError):
        pass
    return [{"name": DEFAULT_PROFILE_NAME, "stops": stops}]


def load_profiles():
    """Return the list of profiles, creating the file from the ini if absent."""
    with profiles_lock:
        path = profiles_path()
        try:
            with open(path, "r") as f:
                return json.load(f)["profiles"]
        except (OSError, ValueError, KeyError):
            profiles = _default_profiles()
            if not path.exists():
                save_profiles(profiles)
            return profiles


def save_profiles(profiles):
    with profiles_lock:
        path = profiles_path()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({"profiles": profiles}, f, indent=2)
        tmp.replace(path)


def parse_stops(stopids, nums):
    """Parse comma-separated form fields into stop dicts; raise ValueError if bad."""
    ids = [i.strip() for i in stopids.split(",") if i.strip()]
    counts = [n.strip() for n in nums.split(",") if n.strip()]
    if not ids:
        raise ValueError("At least one stop id is required.")
    if len(counts) == 1 and len(ids) > 1:
        counts = counts * len(ids)
    if len(ids) != len(counts):
        raise ValueError("Number of stop ids and number of services must match.")
    stops = []
    for stop_id, num in zip(ids, counts):
        if not STOP_ID_RE.match(stop_id):
            raise ValueError(f"Invalid stop id: {stop_id}")
        if not num.isdigit():
            raise ValueError(f"Invalid number of services: {num}")
        stops.append({"stopid": stop_id, "num_services": int(num)})
    return stops


def current_profile_name():
    """Profile selected by this client (cookie), falling back to the first."""
    names = [p["name"] for p in load_profiles()]
    chosen = request.cookies.get(PROFILE_COOKIE)
    if chosen in names:
        return chosen
    return names[0] if names else None


@dataclass
class ClientInfo:
    first_seen: float
    last_seen: float
    request_count: int = 0

    def touch(self):
        self.request_count += 1
        self.last_seen = time.time()


# Track the unique client IDs along with per-client metadata
client_ids_seen = []
client_data = {}
client_data_lock = threading.Lock()

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.logger.propagate = False  # Prevent duplicate logging


def update_stops():
    """Background thread to refresh TFL data and push updates to client."""
    global latest_data
    with app.app_context():
        while True:
            time.sleep(UPDATE_INTERVAL)
            try:
                profiles = load_profiles()
                stop_cache = {}
                by_profile = {}
                for profile in profiles:
                    stops = []
                    for stop in profile["stops"]:
                        key = (stop["stopid"], stop["num_services"])
                        if key not in stop_cache:
                            stop_cache[key] = monitor.get_arrival_times(*key)
                        stops.append(stop_cache[key])
                    by_profile[profile["name"]] = stops
                latest_data["profiles"] = by_profile
                for name, stops in by_profile.items():
                    # Each client's websocket is registered under its profile name.
                    with app.test_request_context():
                        html = render_template("busstop.html", all_stops=stops)
                    turbo.push(turbo.replace(html, target="all_stops"), to=name)
            except Exception as e:
                app.logger.error(f"Error during update_stops: {e}")
                # We do NOT crash; we keep showing old data until the next successful update


@app.context_processor
def inject_all_stops():
    """Make stop data available in all templates."""
    name = current_profile_name()
    return {
        "all_stops": latest_data["profiles"].get(name, []),
        "profiles": [p["name"] for p in load_profiles()],
        "current_profile": name,
        "user_location": request.cookies.get("user_location"),
    }


@turbo.user_id
def turbo_user_id():
    """Group websocket clients by selected profile so each gets its own stops."""
    return current_profile_name() or "default"


@app.before_request
def track_client_id():
    """Keep a record of each unique client_id cookie seen by the server."""
    client_id = request.cookies.get("client_id")
    if not client_id:
        return

    with client_data_lock:
        info = client_data.get(client_id)
        if info is None:
            now = time.time()
            info = ClientInfo(first_seen=now, last_seen=now)
            client_data[client_id] = info
            client_ids_seen.append(client_id)
        info.touch()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/profile/select", methods=["POST"])
def select_profile():
    """Remember the chosen profile in a cookie."""
    name = request.form.get("profile", "")
    if name not in [p["name"] for p in load_profiles()]:
        abort(400)
    response = make_response(redirect(url_for("index")))
    response.set_cookie(PROFILE_COOKIE, name, max_age=60 * 60 * 24 * 365 * 10, samesite="Lax")
    return response


@app.route("/profiles", methods=["GET", "POST"])
def manage_profiles():
    """Create, update and delete profiles."""
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        original = request.form.get("original", "")
        with profiles_lock:
            profiles = load_profiles()
            try:
                if action == "delete":
                    if len(profiles) <= 1:
                        raise ValueError("Cannot delete the last profile.")
                    profiles = [p for p in profiles if p["name"] != original]
                elif action in ("save", "add"):
                    name = request.form.get("name", "").strip()
                    if not name or len(name) > MAX_PROFILE_NAME_LEN:
                        raise ValueError(f"Name must be 1-{MAX_PROFILE_NAME_LEN} characters.")
                    stops = parse_stops(request.form.get("stopids", ""),
                                        request.form.get("num_services", ""))
                    others = [p for p in profiles if p["name"] != (original if action == "save" else None)]
                    if name in [p["name"] for p in others]:
                        raise ValueError("A profile with that name already exists.")
                    new = {"name": name, "stops": stops}
                    if action == "save":
                        profiles = [new if p["name"] == original else p for p in profiles]
                    else:
                        profiles.append(new)
                else:
                    abort(400)
                save_profiles(profiles)
                return redirect(url_for("manage_profiles"))
            except ValueError as e:
                error = str(e)
    rows = [{
        "name": p["name"],
        "stopids": ",".join(s["stopid"] for s in p["stops"]),
        "num_services": ",".join(str(s["num_services"]) for s in p["stops"]),
    } for p in load_profiles()]
    return render_template("profiles.html", rows=rows, error=error), (400 if error else 200)


@app.route("/api/location", methods=["POST"])
def set_location_cookie():
    """Persist user's geolocation (if provided) as a cookie."""
    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lon = data.get("lon")

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid latitude/longitude"}), 400

    response = jsonify({"status": "ok"})
    location_value = f"{lat:.6f},{lon:.6f}"
    # Refresh cookie every 10 minutes so stale locations expire quickly.
    response.set_cookie(
        "user_location",
        location_value,
        max_age=60 * 10,
        samesite="Lax",
    )
    return response


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """View and update stop configuration."""
    if request.method == "POST":
        config_data = request.form["config_data"]
        with open(get_config_path(), "w") as f:
            f.write(config_data)
        return redirect(url_for("index"))
    else:
        with open(get_config_path(), "r") as f:
            config_data = f.read()
        return render_template("admin.html", config_data=config_data)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/stopinfo")
def stopinfo():
    return render_template("stopinfo.html")


@app.errorhandler(404)
def not_found_error(error):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("errors/500.html"), 500


# Start the background thread for live updates
thread = threading.Thread(target=update_stops)
thread.daemon = True
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    app.logger.info("busstop started")
