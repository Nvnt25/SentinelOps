

import uuid

import numpy as np
import pandas as pd


# Illustrative limits and baselines for synthetic data only.
SENSORS = {
    "pressure_bar": {
        "normal": 65.0,
        "noise": 0.8,
        "min": 20.0,
        "max": 100.0,
        "unit": "bar",
    },
    "temperature_c": {
        "normal": 72.0,
        "noise": 1.5,
        "min": -20.0,
        "max": 160.0,
        "unit": "C",
    },
    "vibration_mm_s": {
        "normal": 3.0,
        "noise": 0.25,
        "min": 0.0,
        "max": 50.0,
        "unit": "mm/s",
    },
    "flow_mmscmd": {
        "normal": 45.0,
        "noise": 1.8,
        "min": 0.0,
        "max": 200.0,
        "unit": "million standard m3/day",
    },
    "speed_rpm": {
        "normal": 7200.0,
        "noise": 45.0,
        "min": 0.0,
        "max": 15000.0,
        "unit": "rpm",
    },
}


def generate_telemetry(periods=240, seed=42):
    """Generate synthetic measurements for a compressor station."""
    rng = np.random.default_rng(seed)

    timestamps = pd.date_range(
        end=pd.Timestamp.now(tz="UTC").floor("min"),
        periods=periods,
        freq="min",
    )

    records = []

    for sensor, cfg in SENSORS.items():
        values = cfg["normal"] + rng.normal(
            0, cfg["noise"], periods
        )

        # Simulate gradual drift.
        values += np.linspace(
            0, cfg["noise"] * 0.5, periods
        )

        # Inject an artificial operating anomaly.
        if periods > 60:
            start = periods // 2
            stop = min(start + 8, periods)

            if sensor == "vibration_mm_s":
                values[start:stop] += 3.5
            elif sensor == "temperature_c":
                values[start:stop] += 12
            elif sensor == "pressure_bar":
                values[start:stop] -= 7

        for i, timestamp in enumerate(timestamps):
            records.append({
                "timestamp": timestamp,
                "station_id": "SYN-STATION-01",
                "asset_id": "SYN-COMP-01",
                "sensor": sensor,
                "value": float(values[i]),
                "unit": cfg["unit"],
                "record_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{seed}-{sensor}-{timestamp.isoformat()}",
                )),
                "synthetic": True,
            })

    df = pd.DataFrame(records)

    # Simulate data ingestion defects.
    if len(df) > 100:
        df.loc[10, "value"] = np.nan
        df.loc[35, "value"] = -999.0
        df.loc[50, "timestamp"] = df.loc[49, "timestamp"]

    return df


def assess_data_quality(telemetry):
    """Identify basic data reliability issues."""
    df = telemetry.copy()

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    df["value"] = pd.to_numeric(
        df["value"], errors="coerce"
    )

    df["missing_value"] = df["value"].isna()
    df["invalid_timestamp"] = df["timestamp"].isna()

    df["duplicate_record"] = df.duplicated(
        subset=[
            "station_id",
            "asset_id",
            "sensor",
            "timestamp",
        ],
        keep="first",
    )

    df["out_of_range"] = False

    for sensor, cfg in SENSORS.items():
        mask = df["sensor"].eq(sensor)

        outside_limits = (
            df.loc[mask, "value"].lt(cfg["min"])
            | df.loc[mask, "value"].gt(cfg["max"])
        ).fillna(False)

        df.loc[mask, "out_of_range"] = outside_limits

    flags = [
        "missing_value",
        "invalid_timestamp",
        "duplicate_record",
        "out_of_range",
    ]

    df["quality_issue"] = df[flags].any(axis=1)

    def explain_quality(row):
        reasons = []

        if row["missing_value"]:
            reasons.append("Missing sensor value")
        if row["invalid_timestamp"]:
            reasons.append("Invalid timestamp")
        if row["duplicate_record"]:
            reasons.append("Duplicate sensor timestamp")
        if row["out_of_range"]:
            reasons.append("Reading outside configured limits")

        return "; ".join(reasons) if reasons else "Passed checks"

    df["quality_reason"] = df.apply(
        explain_quality, axis=1
    )

    return df


def detect_anomalies(telemetry, threshold=3.0):
    """Compare readings with their preceding historical baseline."""
    df = telemetry.copy()

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    df["value"] = pd.to_numeric(
        df["value"], errors="coerce"
    )

    df = df.sort_values(
        ["sensor", "timestamp"]
    ).reset_index(drop=True)

    grouped = df.groupby("sensor", sort=False)["value"]

    # Use earlier readings, not the current reading,
    # to calculate the rolling baseline.
    df["baseline"] = grouped.transform(
        lambda s: s.shift(1).rolling(
            30, min_periods=10
        ).median()
    )

    df["rolling_std"] = grouped.transform(
        lambda s: s.shift(1).rolling(
            30, min_periods=10
        ).std()
    )

    df["deviation"] = df["value"] - df["baseline"]

    df["z_score"] = (
        df["deviation"]
        / df["rolling_std"].replace(0, np.nan)
    )

    df["anomaly"] = (
        df["z_score"].abs().ge(threshold)
        & df["value"].notna()
        & df["baseline"].notna()
    ).fillna(False)

    def explain_anomaly(row):
        if not row["anomaly"]:
            return ""

        return (
            f"{row['sensor']} measured {row['value']:.2f}; "
            f"baseline {row['baseline']:.2f}; "
            f"deviation {row['deviation']:+.2f}; "
            f"z-score {row['z_score']:+.2f}"
        )

    df["anomaly_reason"] = df.apply(
        explain_anomaly, axis=1
    )

    return df


def prioritize_alerts(anomalies, quality):
    """Assign transparent triage scores and explanations."""
    alerts = anomalies.loc[
        anomalies["anomaly"]
    ].copy()

    if alerts.empty:
        return pd.DataFrame()

    quality_counts = (
        quality.groupby("sensor")["quality_issue"]
        .sum()
        .to_dict()
    )

    alerts["quality_issue_count"] = (
        alerts["sensor"].map(quality_counts)
        .fillna(0).astype(int)
    )

    alerts["severity_score"] = (
        alerts["z_score"].abs().clip(upper=8)
        / 8 * 70
        + np.where(
            alerts["quality_issue_count"] > 0, 10, 0
        )
        + np.where(
            alerts["z_score"].abs() >= 5, 20, 0
        )
    ).clip(0, 100).round(1)

    alerts["priority"] = pd.cut(
        alerts["severity_score"],
        bins=[-1, 34, 64, 100],
        labels=["Low", "Medium", "High"],
    ).astype(str)

    alerts["alert_id"] = [
        str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{row['asset_id']}-{row['sensor']}-"
            f"{row['timestamp'].isoformat()}",
        ))
        for _, row in alerts.iterrows()
    ]

    alerts["explanation"] = alerts.apply(
        lambda row: (
            f"{row['sensor']} deviated "
            f"{row['deviation']:+.2f} from its baseline "
            f"of {row['baseline']:.2f}. "
            f"Absolute z-score: {abs(row['z_score']):.2f}. "
            f"Quality issues for sensor: "
            f"{row['quality_issue_count']}. "
            f"Priority score: {row['severity_score']:.1f}/100."
        ),
        axis=1,
    )

    return alerts.sort_values(
        ["severity_score", "timestamp"],
        ascending=[False, False],
    ).reset_index(drop=True)