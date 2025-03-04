from flask import Flask, request, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///events.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # in minutes
    recurring = db.Column(db.Boolean, default=False)
    days_of_week = db.Column(db.String(100))  

    def to_dict(self):
        event = {
            'id': self.id,
            'name': self.name,
            'start_date': self.start_date.isoformat(),
            'start_time': self.start_time.strftime("%H:%M"),
            'duration': self.duration,
            'recurring': self.recurring
        }
        if self.recurring and self.days_of_week:
            event['days_of_week'] = json.loads(self.days_of_week)
        return event

with app.app_context():
    db.create_all()

def parse_date(date_str):
    return datetime.strptime(date_str, '%Y-%m-%d').date()

def parse_time(time_str):
    return datetime.strptime(time_str, '%H:%M').time()

def get_event_days(event_data):
    """
    Returns a list of day names on which the event occurs.
    For one-time events, it derives the day of week from the start_date.
    For recurring events, it returns the days provided.
    """
    if event_data.get('recurring'):
        return event_data.get('days_of_week', [])
    else:
        dt = parse_date(event_data['start_date'])
        return [dt.strftime('%A')]

def is_conflict(new_event_data, event_id=None):
    """
    Checks for a scheduling conflict.
    A conflict exists if an existing event (other than the one being updated)
    occurs on any of the same days and at the same start time.
    """
    new_start_time = parse_time(new_event_data['start_time'])
    new_days = get_event_days(new_event_data)
    
    # Query all events except the event being updated (if applicable)
    events = Event.query.filter(Event.id != event_id) if event_id else Event.query
    for event in events:
        if event.recurring and event.days_of_week:
            existing_days = json.loads(event.days_of_week)
        else:
            existing_days = [event.start_date.strftime('%A')]
        
        # If the start times match and there is overlap in the days:
        if event.start_time == new_start_time and set(new_days).intersection(existing_days):
            return True
    return False

@app.route('/events', methods=['GET'])
def get_events():
    events = Event.query.all()
    return jsonify([event.to_dict() for event in events]), 200

@app.route('/events/<int:event_id>', methods=['GET'])
def get_event(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify(event.to_dict()), 200

@app.route('/events', methods=['POST'])
def create_event():
    data = request.get_json()
    required_fields = ['name', 'start_date', 'start_time', 'duration', 'recurring']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing field {field}'}), 400

    if data.get('recurring') and 'days_of_week' not in data:
        return jsonify({'error': 'For recurring events, "days_of_week" must be provided.'}), 400

    if is_conflict(data):
        return jsonify({'error': 'Scheduling conflict: another event is already scheduled at the same day and time.'}), 409

    try:
        start_date = parse_date(data['start_date'])
        start_time = parse_time(data['start_time'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    event = Event(
        name=data['name'],
        start_date=start_date,
        start_time=start_time,
        duration=data['duration'],
        recurring=data['recurring'],
        days_of_week=json.dumps(data['days_of_week']) if data.get('recurring') else None
    )
    db.session.add(event)
    db.session.commit()
    return jsonify(event.to_dict()), 201

@app.route('/events/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.get_json()
    
    # Update fields if provided in request
    for field in ['name', 'start_date', 'start_time', 'duration', 'recurring', 'days_of_week']:
        if field in data:
            if field == 'start_date':
                try:
                    setattr(event, field, parse_date(data[field]))
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400
            elif field == 'start_time':
                try:
                    setattr(event, field, parse_time(data[field]))
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400
            elif field == 'days_of_week':
                # Only update if the event is recurring
                setattr(event, field, json.dumps(data[field]) if data.get('recurring', event.recurring) else None)
            else:
                setattr(event, field, data[field])
    
    # Prepare event data for conflict check
    event_data = {
        'name': event.name,
        'start_date': event.start_date.isoformat(),
        'start_time': event.start_time.strftime("%H:%M"),
        'duration': event.duration,
        'recurring': event.recurring,
        'days_of_week': json.loads(event.days_of_week) if event.days_of_week else []
    }
    if is_conflict(event_data, event_id=event.id):
        return jsonify({'error': 'Scheduling conflict: another event is already scheduled at the same day and time.'}), 409

    db.session.commit()
    return jsonify(event.to_dict()), 200

if __name__ == '__main__':
    app.run(debug=True)