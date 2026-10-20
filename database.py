import json
import sqlite3
from pathlib import Path

import pandas as pd


# Store the database in the SentinelOps project folder.
DB_PATH = Path(__file__).with_name("sentinelops.db")


def connect():
    """Open a database connection with named-column access."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    """Create the tables needed by SentinelOps."""
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
                record_id TEXT PRIMARY KEY,
                timestamp TEXT,
                station_id TEXT,
                asset_id TEXT,
                sensor TEXT,
                value REAL,
                unit TEXT,
                synthetic INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                sensor TEXT NOT NULL,
                observed_value REAL,
                baseline REAL,
                deviation REAL,
                z_score REAL,
                severity_score REAL,
                priority TEXT,
                explanation TEXT,
                evidence_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS investigations (
                alert_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'Open',
                owner TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (alert_id)
                    REFERENCES alerts(alert_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (alert_id)
                    REFERENCES alerts(alert_id)
            );
        """)


def save_telemetry(frame: pd.DataFrame):
    """Save synthetic sensor readings without duplicating record IDs."""
    rows = []

    for _, row in frame.iterrows():
        timestamp = row["timestamp"]

        rows.append((
            str(row["record_id"]),
            None if pd.isna(timestamp) else str(timestamp),
            str(row["station_id"]),
            str(row["asset_id"]),
            str(row["sensor"]),
            None if pd.isna(row["value"])
            else float(row["value"]),
            str(row["unit"]),
            int(bool(row.get("synthetic", True))),
        ))

    with connect() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO telemetry (
                record_id, timestamp, station_id, asset_id,
                sensor, value, unit, synthetic
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


def save_alerts(alerts: pd.DataFrame):
    """Persist alerts and create a corresponding investigation."""
    if alerts.empty:
        return

    with connect() as conn:
        for _, row in alerts.iterrows():
            evidence = {
                "timestamp": str(row["timestamp"]),
                "asset_id": str(row["asset_id"]),
                "sensor": str(row["sensor"]),
                "observed_value": float(row["value"]),
                "baseline": float(row["baseline"]),
                "deviation": float(row["deviation"]),
                "z_score": float(row["z_score"]),
                "quality_issue_count": int(
                    row["quality_issue_count"]
                ),
                "detection_method":
                    "rolling_median_and_standard_deviation",
                "threshold": 3.0,
                "synthetic": True,
            }

            conn.execute("""
                INSERT OR IGNORE INTO alerts (
                    alert_id, timestamp, asset_id, sensor,
                    observed_value, baseline, deviation, z_score,
                    severity_score, priority, explanation,
                    evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(row["alert_id"]),
                str(row["timestamp"]),
                str(row["asset_id"]),
                str(row["sensor"]),
                float(row["value"]),
                float(row["baseline"]),
                float(row["deviation"]),
                float(row["z_score"]),
                float(row["severity_score"]),
                str(row["priority"]),
                str(row["explanation"]),
                json.dumps(evidence),
            ))

            conn.execute("""
                INSERT OR IGNORE INTO investigations (alert_id)
                VALUES (?)
            """, (str(row["alert_id"]),))


def load_alerts():
    """Load alerts together with their investigation details."""
    with connect() as conn:
        return pd.read_sql_query("""
            SELECT
                a.*,
                i.status,
                i.owner,
                i.notes,
                i.outcome,
                i.updated_at
            FROM alerts AS a
            LEFT JOIN investigations AS i
                ON a.alert_id = i.alert_id
            ORDER BY
                a.severity_score DESC,
                a.timestamp DESC
        """, conn)


def load_telemetry():
    """Retrieve all persisted sensor readings."""
    with connect() as conn:
        return pd.read_sql_query("""
            SELECT *
            FROM telemetry
            ORDER BY timestamp
        """, conn)


def load_audit_log(alert_id):
    """Retrieve the recorded investigation changes for an alert."""
    with connect() as conn:
        return pd.read_sql_query("""
            SELECT action, details, actor, created_at
            FROM audit_log
            WHERE alert_id = ?
            ORDER BY id DESC
        """, conn, params=(alert_id,))


def update_investigation(
    alert_id: str,
    status: str,
    owner: str,
    notes: str,
    outcome: str,
    actor: str = "Demo Analyst",
):
    """Update an investigation and record the change."""
    allowed_statuses = {
        "Open",
        "In Review",
        "Escalated",
        "Resolved",
    }

    allowed_outcomes = {
        "",
        "Confirmed Anomaly",
        "Sensor/Data Issue",
        "Expected Operating Variation",
        "False Positive",
        "Unable to Determine",
    }

    if status not in allowed_statuses:
        raise ValueError("Invalid investigation status.")

    if outcome not in allowed_outcomes:
        raise ValueError("Invalid investigation outcome.")

    if status == "Resolved" and not outcome:
        raise ValueError(
            "Choose an outcome before resolving the investigation."
        )

    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM alerts WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()

        if exists is None:
            raise ValueError("Alert does not exist.")

        updated = conn.execute("""
            UPDATE investigations
            SET
                status = ?,
                owner = ?,
                notes = ?,
                outcome = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE alert_id = ?
        """, (
            status,
            owner.strip(),
            notes.strip(),
            outcome,
            alert_id,
        ))

        if updated.rowcount != 1:
            raise ValueError("Investigation record does not exist.")

        conn.execute("""
            INSERT INTO audit_log (
                alert_id, action, details, actor
            )
            VALUES (?, ?, ?, ?)
        """, (
            alert_id,
            "INVESTIGATION_UPDATED",
            json.dumps({
                "status": status,
                "owner": owner.strip(),
                "notes": notes.strip(),
                "outcome": outcome,
            }),
            actor,
        ))