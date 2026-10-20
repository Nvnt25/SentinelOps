import json

import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    initialize_database,
    save_telemetry,
    save_alerts,
    load_alerts,
    load_telemetry,
    load_audit_log,
    update_investigation,
)

from engine import (
    generate_telemetry,
    assess_data_quality,
    detect_anomalies,
    prioritize_alerts,
)


# --------------------------------------------------
# 1. APPLICATION CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="SentinelOps",
    page_icon="📡",
    layout="wide",
)

st.title("📡 SentinelOps")
st.caption("Predictive Insights & Operational Intelligence Platform")

st.info(
    "Independent portfolio project. All operational data is synthetic. "
    "This is not a TC Energy system and is not intended for operational control."
)

initialize_database()


# --------------------------------------------------
# 2. SIDEBAR AND SIMULATION CONTROLS
# --------------------------------------------------

st.sidebar.title("SentinelOps")
st.sidebar.caption("Synthetic compressor station monitoring")
st.sidebar.warning("DEMO ENVIRONMENT — SYNTHETIC DATA ONLY")

page = st.sidebar.radio(
    "Navigation",
    [
        "Overview",
        "Telemetry & Quality",
        "Alert Triage",
        "Investigation History",
    ],
)

st.sidebar.divider()
st.sidebar.subheader("Simulation controls")

seed = st.sidebar.number_input(
    "Simulation seed",
    min_value=1,
    max_value=999999,
    value=42,
    step=1,
)

periods = st.sidebar.slider(
    "Simulation duration (minutes)",
    min_value=60,
    max_value=720,
    value=240,
    step=60,
)

if st.sidebar.button("Generate / refresh simulation"):
    with st.spinner("Generating synthetic telemetry..."):
        telemetry = generate_telemetry(
            periods=int(periods),
            seed=int(seed),
        )

        quality = assess_data_quality(telemetry)
        anomalies = detect_anomalies(telemetry)
        alerts = prioritize_alerts(anomalies, quality)

        save_telemetry(telemetry)
        save_alerts(alerts)

    st.sidebar.success(
        f"Processed {len(telemetry)} synthetic readings."
    )
    st.rerun()


# --------------------------------------------------
# 3. INITIALIZE DATA ON FIRST RUN
# --------------------------------------------------

telemetry = load_telemetry()

if telemetry.empty:
    telemetry = generate_telemetry(
        periods=int(periods),
        seed=int(seed),
    )

    quality = assess_data_quality(telemetry)
    anomalies = detect_anomalies(telemetry)
    alerts = prioritize_alerts(anomalies, quality)

    save_telemetry(telemetry)
    save_alerts(alerts)

# Reload stored records after initialization.
telemetry = load_telemetry()
all_alerts = load_alerts()

if telemetry.empty:
    st.error("No telemetry is available.")
    st.stop()

telemetry["timestamp"] = pd.to_datetime(
    telemetry["timestamp"],
    utc=True,
    errors="coerce",
)

telemetry["value"] = pd.to_numeric(
    telemetry["value"],
    errors="coerce",
)

# Recalculate data-quality metrics from stored telemetry.
quality = assess_data_quality(telemetry)


# --------------------------------------------------
# 4. CALCULATE DASHBOARD METRICS
# --------------------------------------------------

total_readings = len(telemetry)
quality_issues = int(quality["quality_issue"].sum())

quality_percentage = (
    100 * (total_readings - quality_issues) / total_readings
    if total_readings else 100
)

if all_alerts.empty:
    open_alerts = all_alerts
    high_priority_count = 0
    resolved_count = 0
else:
    open_alerts = all_alerts[
        all_alerts["status"].isin(
            ["Open", "In Review", "Escalated"]
        )
    ]

    high_priority_count = int(
        (open_alerts["priority"] == "High").sum()
    )

    resolved_count = int(
        (all_alerts["status"] == "Resolved").sum()
    )


# --------------------------------------------------
# 5. OVERVIEW PAGE
# --------------------------------------------------

if page == "Overview":

    st.header("Operations overview")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Telemetry records",
        f"{total_readings:,}",
    )

    col2.metric(
        "Open investigations",
        len(open_alerts),
    )

    col3.metric(
        "High-priority open alerts",
        high_priority_count,
    )

    col4.metric(
        "Basic data quality",
        f"{quality_percentage:.1f}%",
    )

    st.divider()
    st.subheader("Sensor performance")

    sensors = sorted(
        telemetry["sensor"].dropna().unique()
    )

    selected_sensor = st.selectbox(
        "Choose a sensor",
        sensors,
    )

    sensor_data = telemetry[
        telemetry["sensor"] == selected_sensor
    ].sort_values("timestamp")

    chart = px.line(
        sensor_data,
        x="timestamp",
        y="value",
        title=f"{selected_sensor} over time",
        labels={
            "timestamp": "Timestamp",
            "value": "Measurement",
        },
    )

    chart.update_layout(hovermode="x unified")

    st.plotly_chart(
        chart,
        use_container_width=True,
    )

    st.subheader("Alert priority distribution")

    if all_alerts.empty:
        st.success("No alerts have been recorded.")
    else:
        priority_counts = (
            all_alerts.groupby("priority")
            .size()
            .reindex(
                ["High", "Medium", "Low"],
                fill_value=0,
            )
            .rename("Alerts")
            .reset_index()
        )

        priority_chart = px.bar(
            priority_counts,
            x="priority",
            y="Alerts",
            color="priority",
            category_orders={
                "priority": ["High", "Medium", "Low"]
            },
            title="Recorded alerts by priority",
        )

        st.plotly_chart(
            priority_chart,
            use_container_width=True,
        )

    st.subheader("Latest alerts")

    if all_alerts.empty:
        st.write("No alerts available.")
    else:
        st.dataframe(
            all_alerts[
                [
                    "timestamp",
                    "sensor",
                    "observed_value",
                    "baseline",
                    "priority",
                    "severity_score",
                    "status",
                ]
            ].head(15),
            use_container_width=True,
            hide_index=True,
        )


# --------------------------------------------------
# 6. TELEMETRY AND DATA QUALITY PAGE
# --------------------------------------------------

elif page == "Telemetry & Quality":

    st.header("Telemetry & data reliability")

    sensor_options = [
        "All"
    ] + sorted(quality["sensor"].dropna().unique())

    selected_sensor = st.selectbox(
        "Filter by sensor",
        sensor_options,
    )

    view = quality.copy()

    if selected_sensor != "All":
        view = view[
            view["sensor"] == selected_sensor
        ]

    col1, col2 = st.columns(2)

    col1.metric(
        "Records inspected",
        len(view),
    )

    col2.metric(
        "Records with quality issues",
        int(view["quality_issue"].sum()),
    )

    st.subheader("Quality findings")

    st.dataframe(
        view[
            [
                "timestamp",
                "asset_id",
                "sensor",
                "value",
                "unit",
                "quality_issue",
                "quality_reason",
            ]
        ].sort_values(
            "timestamp",
            ascending=False,
        ),
        use_container_width=True,
        hide_index=True,
    )

    flags = [
        "missing_value",
        "invalid_timestamp",
        "duplicate_record",
        "out_of_range",
    ]

    breakdown = pd.DataFrame({
        "Issue": flags,
        "Records": [
            int(view[flag].sum())
            for flag in flags
        ],
    })

    quality_chart = px.bar(
        breakdown,
        x="Issue",
        y="Records",
        title="Data-quality issue breakdown",
    )

    st.plotly_chart(
        quality_chart,
        use_container_width=True,
    )

    st.download_button(
        "Download quality report (CSV)",
        data=view.to_csv(index=False).encode("utf-8"),
        file_name="sentinelops_quality_report.csv",
        mime="text/csv",
    )


# --------------------------------------------------
# 7. ALERT TRIAGE PAGE
# --------------------------------------------------

elif page == "Alert Triage":

    st.header("Alert triage")

    if all_alerts.empty:
        st.success("No alerts have been recorded.")
        st.stop()

    priorities = st.multiselect(
        "Filter by priority",
        ["High", "Medium", "Low"],
        default=["High", "Medium", "Low"],
    )

    statuses = st.multiselect(
        "Filter by investigation status",
        ["Open", "In Review", "Escalated", "Resolved"],
        default=["Open", "In Review", "Escalated"],
    )

    filtered = all_alerts[
        all_alerts["priority"].isin(priorities)
        & all_alerts["status"].isin(statuses)
    ]

    st.dataframe(
        filtered[
            [
                "alert_id",
                "timestamp",
                "sensor",
                "observed_value",
                "baseline",
                "deviation",
                "severity_score",
                "priority",
                "status",
                "owner",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    if filtered.empty:
        st.info("No alerts match your filters.")
        st.stop()

    selected_id = st.selectbox(
        "Select an alert",
        filtered["alert_id"].tolist(),
        format_func=lambda alert_id: (
            f"{filtered.loc[filtered['alert_id'] == alert_id, 'priority'].iloc[0]}"
            f" | {filtered.loc[filtered['alert_id'] == alert_id, 'sensor'].iloc[0]}"
            f" | {alert_id[:8]}"
        ),
    )

    alert = all_alerts[
        all_alerts["alert_id"] == selected_id
    ].iloc[0]

    st.subheader("Why was this alert generated?")
    st.write(alert["explanation"])

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Observed value",
        f"{alert['observed_value']:.2f}",
    )

    col2.metric(
        "Historical baseline",
        f"{alert['baseline']:.2f}",
    )

    col3.metric(
        "Priority score",
        f"{alert['severity_score']:.1f}/100",
    )

    st.subheader("Traceable evidence")

    evidence = json.loads(alert["evidence_json"])
    st.json(evidence)

    history = telemetry[
        (telemetry["sensor"] == alert["sensor"])
        & (telemetry["asset_id"] == alert["asset_id"])
    ].sort_values("timestamp").tail(100)

    history_chart = px.line(
        history,
        x="timestamp",
        y="value",
        title=f"Recent readings: {alert['sensor']}",
    )

    history_chart.add_hline(
        y=float(alert["baseline"]),
        line_dash="dash",
        annotation_text="Stored alert baseline",
    )

    st.plotly_chart(
        history_chart,
        use_container_width=True,
    )

    st.subheader("Investigation workspace")

    status_options = [
        "Open",
        "In Review",
        "Escalated",
        "Resolved",
    ]

    outcome_options = [
        "",
        "Confirmed Anomaly",
        "Sensor/Data Issue",
        "Expected Operating Variation",
        "False Positive",
        "Unable to Determine",
    ]

    current_status = (
        alert["status"]
        if alert["status"] in status_options
        else "Open"
    )

    current_outcome = (
        alert["outcome"]
        if alert["outcome"] in outcome_options
        else ""
    )

    with st.form("investigation_form"):

        owner = st.text_input(
            "Assigned analyst",
            value=alert["owner"] or "",
        )

        status = st.selectbox(
            "Investigation status",
            status_options,
            index=status_options.index(current_status),
        )

        notes = st.text_area(
            "Investigation notes",
            value=alert["notes"] or "",
            placeholder=(
                "Document the checks performed and evidence reviewed."
            ),
        )

        outcome = st.selectbox(
            "Investigation outcome",
            outcome_options,
            index=outcome_options.index(current_outcome),
            format_func=lambda value: value or "Not decided",
        )

        submitted = st.form_submit_button(
            "Save investigation",
            type="primary",
        )

    if submitted:
        try:
            update_investigation(
                alert_id=selected_id,
                status=status,
                owner=owner,
                notes=notes,
                outcome=outcome,
            )

            st.success("Investigation saved successfully.")
            st.rerun()

        except ValueError as error:
            st.error(str(error))

    st.subheader("Investigation audit history")

    audit = load_audit_log(selected_id)

    if audit.empty:
        st.caption("No investigation changes recorded yet.")
    else:
        st.dataframe(
            audit,
            use_container_width=True,
            hide_index=True,
        )


# --------------------------------------------------
# 8. INVESTIGATION HISTORY PAGE
# --------------------------------------------------

elif page == "Investigation History":

    st.header("Investigation history")

    if all_alerts.empty:
        st.info("There are no recorded investigations yet.")
        st.stop()

    completed = all_alerts[
        all_alerts["status"] == "Resolved"
    ]

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Total alerts",
        len(all_alerts),
    )

    col2.metric(
        "Resolved investigations",
        len(completed),
    )

    col3.metric(
        "Unresolved investigations",
        int(
            (all_alerts["status"] != "Resolved").sum()
        ),
    )

    st.subheader("Investigation register")

    st.dataframe(
        all_alerts[
            [
                "alert_id",
                "timestamp",
                "sensor",
                "priority",
                "status",
                "owner",
                "outcome",
                "notes",
                "updated_at",
            ]
        ].sort_values(
            "updated_at",
            ascending=False,
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Recorded outcomes")

    outcome_counts = (
        all_alerts["outcome"]
        .replace("", "Not recorded")
        .fillna("Not recorded")
        .value_counts()
        .rename_axis("Outcome")
        .reset_index(name="Count")
    )

    outcome_chart = px.bar(
        outcome_counts,
        x="Outcome",
        y="Count",
        title="Investigation dispositions",
    )

    st.plotly_chart(
        outcome_chart,
        use_container_width=True,
    )

    st.download_button(
        "Export investigation register (CSV)",
        data=all_alerts.to_csv(index=False).encode("utf-8"),
        file_name="sentinelops_investigations.csv",
        mime="text/csv",
    )
