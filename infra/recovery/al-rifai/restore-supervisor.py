#!/usr/bin/env python3
"""C2 fixed-target adapter preparation. OS/database transport is hard locked."""
import argparse
import datetime
import hashlib
import json
import math
import os
import stat
import threading
import time
from pathlib import Path

TARGET = "alrifai_restore_20261008_053528"
CLUSTER = "7694012476208082978"
CONTAINER = "63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6"
IMAGE = "sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
ARCHIVE = "/var/backups/vps/postgres/alrifai-current-baseline-20261008T053528Z.dump"
ARCHIVE_SHA = "5f12fdeff34aac57e733af012e52daebb97f44fa7d56d962166fa4c85debcded"
APP_NAME = "alrifai-qual-restore-20261008-053528"
LIVE_EXECUTION_ENABLED = False
FINGERPRINTS = {
    "state": "96f4fe553fdd54d5e10869696dd9e5ded3e9da434c4fe4cc37496599be0464ba",
    "snapshots": "3590e6eba9081e3f0bc79c90b35375a636b76b16fe3a4043adad4edf93bb0757",
    "catalog": "146c5dbf5f3a2f88ade4dbf893eeba189035b03b99b5cb798ae8531060f5a174",
}

class SafetyStop(Exception):
    pass

def require(condition, code):
    if not condition:
        raise SafetyStop(code)

def load_attestation():
    baseline = json.loads(Path(__file__).with_name("baseline-attestation.json").read_text())
    require(baseline.get("fingerprints") == FINGERPRINTS, "BASELINE")
    require(baseline.get("target") == TARGET and baseline.get("cluster") == CLUSTER, "BASELINE_IDENTITY")
    require(baseline.get("archive", {}).get("sha256") == ARCHIVE_SHA, "ARCHIVE_IDENTITY")
    require(baseline.get("provenance", {}).get("classification") == "RECONSTRUCTED_NOT_ORIGINAL_STAGE_B", "PROVENANCE")
    sql = Path(__file__).with_name("read-plan.sql").read_bytes()
    require(hashlib.sha256(sql).hexdigest() == baseline.get("readPlanSHA256"), "READ_PLAN_CHANGED")
    return baseline

def proposed_plan():
    """Return argv arrays only. Never execute them."""
    return {
        "mode": "PLAN_ONLY", "liveExecutionEnabled": False,
        "target": TARGET, "cluster": CLUSTER, "archive": ARCHIVE,
        "archiveSHA256": ARCHIVE_SHA,
        "createdb": ["docker", "exec", CONTAINER, "createdb", "-w", "-h",
            "/var/run/postgresql", "-p", "5432", "-U", "vps_pg_admin",
            "--maintenance-db=postgres", "--template=template0",
            "--owner=alrifai_app", "--encoding=UTF8", "--locale-provider=libc",
            "--lc-collate=en_US.utf8", "--lc-ctype=en_US.utf8", TARGET],
        "restore": ["docker", "exec", "-i", "-e", "PGAPPNAME=" + APP_NAME,
            CONTAINER, "pg_restore", "-w", "-h", "/var/run/postgresql",
            "-p", "5432", "-U", "vps_pg_admin", "--role=alrifai_app",
            "--no-owner", "--single-transaction", "--exit-on-error",
            "--dbname=" + TARGET],
        "restoreInput": ARCHIVE,
        "requiredOwnerLimits": ["minimumFreeBytes", "minimumAvailableMemoryBytes",
            "maximumRestoreSeconds", "monitorIntervalSeconds"],
        "preflight": ["exact container/image/cluster", "explicit administrative identity",
            "archive hash/type/mode/owner and protected destination",
            "target absent and unused by application", "versions 16.15",
            "production configuration unchanged", "health before execution",
            "no conflicting maintenance", "approved window and resource limits",
            "fresh read-only production state/catalog fingerprints"],
        "monitoring": ["start before restore", "CPU/memory/disk/WAL/locks/health",
            "capture unique restore PID and backend_start in approved start window",
            "independently revalidate cluster and full session identity before any signal"],
        "onFailure": ["stop", "no retry or fallback", "retain database and evidence",
            "do not restart production", "commit outcome uncertain on connection loss"],
        "postflight": ["guarded read-only restored comparisons",
            "supplementary assertions", "production unchanged comparisons",
            "health/start timestamps/config", "no application connection to target"],
        "cancellation": "UNAVAILABLE: requires separately reviewed adapter and explicit owner authorization",
        "cleanup": "UNAVAILABLE: separate exact-object approval required",
    }

def validate_mock_preflight(state, approval, limits):
    """Pure predicate for offline tests, not an execution authorization mechanism."""
    require(approval.get("stage") == "C" and approval.get("target") == TARGET
            and approval.get("archiveSHA256") == ARCHIVE_SHA, "OWNER_APPROVAL")
    require(set(limits) == {"minimumFreeBytes", "minimumAvailableMemoryBytes",
                          "maximumRestoreSeconds", "monitorIntervalSeconds"}, "LIMITS")
    require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                for v in limits.values()), "LIMITS")
    require(state.get("container") == CONTAINER and state.get("image") == IMAGE
            and state.get("cluster") == CLUSTER, "IDENTITY")
    require(state.get("target") == TARGET and state["target"] != "alrifai", "TARGET")
    require(state.get("targetExists") is False, "TARGET_EXISTS")
    require(state.get("archiveSHA256") == ARCHIVE_SHA, "ARCHIVE")
    require(state.get("version") == "16.15", "VERSION")
    require(state.get("adminDatabase") == "postgres" and state.get("adminUser") == "vps_pg_admin",
            "ADMIN_IDENTITY")
    require(state.get("appTarget") == "alrifai", "APPLICATION_TARGET")
    require(state.get("healthy") is True and state.get("conflictingMaintenance") is False, "HEALTH_OR_MAINTENANCE")
    require(state.get("permissionsOK") is True, "PERMISSIONS")
    require(state.get("windowOK") is True, "WINDOW")
    require(state.get("freeBytes", 0) >= limits["minimumFreeBytes"]
            and state.get("availableMemoryBytes", 0) >= limits["minimumAvailableMemoryBytes"], "CAPACITY")
    require(state.get("productionFingerprints") == FINGERPRINTS, "PRODUCTION_BASELINE")

def match_restore_session(cluster, sessions, captured, approved_window):
    """Pure monitoring matcher. It does not cancel or terminate anything."""
    require(cluster == CLUSTER, "CANCEL_CLUSTER")
    require(isinstance(captured.get("pid"), int) and not isinstance(captured["pid"], bool)
            and captured["pid"] > 0, "CANCEL_PID")
    require(captured.get("backendStart") is not None, "CANCEL_START")
    def timestamp(value):
        require(isinstance(value, str), "CANCEL_TIMESTAMP")
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise SafetyStop("CANCEL_TIMESTAMP")
        require(parsed.tzinfo is not None, "CANCEL_TIMESTAMP")
        return parsed
    require(len(approved_window) == 2, "CANCEL_WINDOW")
    require(timestamp(approved_window[0]) <= timestamp(captured["backendStart"])
            <= timestamp(approved_window[1]), "CANCEL_WINDOW")
    candidates = [s for s in sessions
        if {"database", "applicationName", "user", "backendType", "clientAddress", "pid", "backendStart"}.issubset(s)
        and s.get("database") == TARGET and s.get("database") != "alrifai"
        and s.get("applicationName") == APP_NAME and s.get("user") == "vps_pg_admin"
        and s.get("backendType") == "client backend" and s.get("clientAddress") is None]
    require(len(candidates) == 1, "CANCEL_AMBIGUOUS")
    candidate = candidates[0]
    require(candidate.get("pid") == captured["pid"]
            and candidate.get("backendStart") == captured["backendStart"], "CANCEL_SESSION_CHANGED")
    return {"pid": candidate["pid"], "backendStart": candidate["backendStart"],
            "database": TARGET, "applicationName": APP_NAME, "cluster": CLUSTER,
            "action": "DESIGN_ONLY_NO_SIGNAL"}

def offline_simulate(state, approval, limits, failure=None):
    """Mock lifecycle, returning labels only. No executable transport exists."""
    trace = []
    try:
        validate_mock_preflight(state, approval, limits)
        trace.append("preflight_passed")
        if failure == "creation":
            raise SafetyStop("MOCK_CREATION_FAILURE")
        trace.append("mock_target_created")
        trace.append("mock_monitor_started")
        if failure in ("restore", "connection_loss", "pressure", "health", "duration"):
            raise SafetyStop("MOCK_" + failure.upper())
        trace.append("mock_restore_completed")
        if failure in ("integrity", "supplemental", "production_changed"):
            raise SafetyStop("MOCK_" + failure.upper())
        trace.append("mock_verification_passed")
        return {"status": "MOCK_PASS", "trace": trace, "cleanup": False, "realCommands": 0}
    except SafetyStop as error:
        return {"status": "MOCK_STOP", "code": str(error), "trace": trace,
                "partialTargetMayRemain": "mock_target_created" in trace,
                "retry": False, "cleanup": False, "realCommands": 0}

def self_test():
    import copy
    limits = dict(minimumFreeBytes=100, minimumAvailableMemoryBytes=100,
                  maximumRestoreSeconds=10, monitorIntervalSeconds=1)
    state = dict(container=CONTAINER, image=IMAGE, cluster=CLUSTER, target=TARGET,
        targetExists=False, archiveSHA256=ARCHIVE_SHA, version="16.15",
        adminDatabase="postgres", adminUser="vps_pg_admin", appTarget="alrifai",
        healthy=True, conflictingMaintenance=False, permissionsOK=True, windowOK=True,
        freeBytes=1000, availableMemoryBytes=1000, productionFingerprints=FINGERPRINTS.copy())
    approval = dict(stage="C", target=TARGET, archiveSHA256=ARCHIVE_SHA)
    passed = []
    def check(name, condition):
        require(condition, "SELF_TEST")
        passed.append(name)
    check("default plan has no live adapter", proposed_plan()["liveExecutionEnabled"] is False)
    check("mock success", offline_simulate(state, approval, limits)["status"] == "MOCK_PASS")
    for key, value in [
        ("cluster", "wrong"), ("container", "wrong"), ("target", "alrifai"),
        ("targetExists", True), ("archiveSHA256", "wrong"), ("version", "wrong"),
        ("adminDatabase", "alrifai"), ("adminUser", "wrong"), ("appTarget", TARGET),
        ("healthy", False), ("conflictingMaintenance", True), ("permissionsOK", False),
        ("windowOK", False), ("freeBytes", 0), ("availableMemoryBytes", 0),
        ("productionFingerprints", {})]:
        bad = copy.deepcopy(state)
        bad[key] = value
        result = offline_simulate(bad, approval, limits)
        check("preflight rejects " + key, result["status"] == "MOCK_STOP" and not result["trace"])
    check("approval absent", offline_simulate(state, {}, limits)["status"] == "MOCK_STOP")
    check("limits absent", offline_simulate(state, approval, {})["status"] == "MOCK_STOP")
    for failure in ["creation", "restore", "connection_loss", "pressure", "health",
                    "duration", "integrity", "supplemental", "production_changed"]:
        result = offline_simulate(state, approval, limits, failure)
        check("failure " + failure, result["status"] == "MOCK_STOP"
              and result["realCommands"] == 0 and not result["retry"] and not result["cleanup"])
    session = dict(database=TARGET, applicationName=APP_NAME, user="vps_pg_admin",
        backendType="client backend", clientAddress=None, pid=123,
        backendStart="2026-10-08T06:00:00Z")
    captured = dict(pid=123, backendStart=session["backendStart"])
    window = ("2026-10-08T05:59:00Z", "2026-10-08T06:01:00Z")
    check("exact session design only", match_restore_session(CLUSTER, [session], captured, window)["action"] == "DESIGN_ONLY_NO_SIGNAL")
    cases = [
        ("production session", CLUSTER, [{**session, "database": "alrifai"}], captured),
        ("wrong cluster", "wrong", [session], captured),
        ("duplicate sessions", CLUSTER, [session, session], captured),
        ("missing session", CLUSTER, [], captured),
        ("reused pid", CLUSTER, [{**session, "backendStart": "2026-10-08T06:00:01Z"}], captured),
        ("wrong application", CLUSTER, [{**session, "applicationName": "other"}], captured),
        ("wrong user", CLUSTER, [{**session, "user": "alrifai_app"}], captured),
        ("wrong pid", CLUSTER, [session], {**captured, "pid": 124}),
        ("missing client identity", CLUSTER, [{k: v for k, v in session.items() if k != "clientAddress"}], captured),
        ("malformed timestamp", CLUSTER, [session], {**captured, "backendStart": "invalid"}),
    ]
    for name, cluster, sessions, cap in cases:
        try:
            match_restore_session(cluster, sessions, cap, window)
        except SafetyStop:
            passed.append("cancellation rejects " + name)
        else:
            raise SafetyStop("SELF_TEST")
    return {"status": "PASS", "tests": len(passed), "cases": passed,
            "realCommands": 0, "databaseConnections": 0, "signals": 0}


# C2: this is an adapter orchestration implementation with an inert OS boundary.
# The lock is unconditional: changing LIVE_EXECUTION_ENABLED, argv, approval or
# environment cannot unlock it. A reviewed source revision is required.
def launch_live(*args, **kwargs):
    raise SafetyStop("C2_LIVE_TRANSPORT_LOCKED")

def process_environment():
    """Exact host environment proposal; never inherit PG*, loader or Docker vars."""
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}

def fixed_command(operation, target, cluster):
    require(target == TARGET and target != "alrifai", "TARGET")
    require(cluster == CLUSTER, "IDENTITY")
    require(operation in ("createdb", "restore"), "COMMAND")
    argv = proposed_plan()[operation][:]
    argv[0] = "/usr/bin/docker"
    return argv

def validate_command(operation, argv, target, cluster, environment):
    require(type(argv) is list and argv == fixed_command(operation, target, cluster), "COMMAND")
    require(environment == process_environment(), "ENVIRONMENT")

LIMIT_KEYS = {"minimumFreeBytes", "minimumAvailableMemoryBytes", "maximumRestoreSeconds",
              "monitorIntervalSeconds", "maximumCpuPercent", "maximumWalBytes", "maximumLockSeconds"}

def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)

def validate_limits(limits):
    require(type(limits) is dict and set(limits) == LIMIT_KEYS, "LIMITS")
    require(all(finite_number(v) and v > 0 for v in limits.values()), "LIMITS")
    require(limits["maximumCpuPercent"] <= 100 and
            limits["monitorIntervalSeconds"] <= limits["maximumRestoreSeconds"], "LIMITS")

def archive_observation(facts):
    """Validate mock/future collector facts; does not open the archive in C2."""
    require(type(facts) is dict and facts.get("exists") is True, "ARCHIVE_MISSING")
    require(facts.get("path") == ARCHIVE and facts.get("sha256") == ARCHIVE_SHA
            and facts.get("bytes") == 1608294, "ARCHIVE")
    require(facts.get("regular") is True and facts.get("symlink") is False
            and facts.get("uid") == 0 and facts.get("gid") == 0
            and facts.get("mode") == "0600" and facts.get("format") == "CUSTOM", "ARCHIVE_PROPERTIES")

def monitor_sample(sample, previous, limits):
    validate_limits(limits)
    fields = ("elapsedSeconds", "freeBytes", "availableMemoryBytes", "cpuPercent", "walBytes", "lockSeconds")
    require(type(sample) is dict and all(finite_number(sample.get(k)) and sample[k] >= 0 for k in fields), "MONITOR_SAMPLE")
    require(sample.get("healthy") is True, "MONITOR_HEALTH")
    elapsed = sample["elapsedSeconds"]
    require(elapsed >= previous and elapsed - previous <= limits["monitorIntervalSeconds"], "MONITOR_GAP")
    require(elapsed <= limits["maximumRestoreSeconds"], "MONITOR_DURATION")
    require(sample["freeBytes"] >= limits["minimumFreeBytes"] and
            sample["availableMemoryBytes"] >= limits["minimumAvailableMemoryBytes"], "MONITOR_CAPACITY")
    require(sample["cpuPercent"] <= limits["maximumCpuPercent"] and
            sample["walBytes"] <= limits["maximumWalBytes"] and
            sample["lockSeconds"] <= limits["maximumLockSeconds"], "MONITOR_PRESSURE")
    return elapsed

def preflight(state, archive, approval, limits):
    validate_limits(limits)
    validate_mock_preflight(state, approval, {k: limits[k] for k in
        ("minimumFreeBytes", "minimumAvailableMemoryBytes", "maximumRestoreSeconds", "monitorIntervalSeconds")})
    require(approval.get("cluster") == CLUSTER and approval.get("actions") == ["create", "restore", "verify"], "OWNER_APPROVAL")
    require(state.get("clientVersion") == "16.15" and state.get("configUnchanged") is True
            and state.get("targetSessions") == 0, "PREFLIGHT_BOUNDARY")
    archive_observation(archive)

def cancellation_request(action, approval, cluster, sessions, captured, window):
    require(action in ("cancel", "terminate"), "SIGNAL_ACTION")
    require(type(approval) is dict and approval.get("stage") == "C"
            and approval.get("target") == TARGET and approval.get("cluster") == CLUSTER
            and approval.get("archiveSHA256") == ARCHIVE_SHA
            and action in approval.get("signals", []), "SIGNAL_NOT_AUTHORIZED")
    matched = match_restore_session(cluster, sessions, captured, window)
    return {**matched, "action": "MOCK_" + action.upper()}

class MockTransport:
    """Synthetic process/database fixture only: no callbacks or OS transport."""
    def __init__(self, outcomes=None):
        self.outcomes = dict(outcomes or {})
        self.calls = []

    def command(self, operation, argv, environment):
        validate_command(operation, argv, TARGET, CLUSTER, environment)
        self.calls.append(operation)
        result = self.outcomes.get(operation, {"returncode": 0})
        if isinstance(result, Exception):
            raise result
        return result

class FixedTargetAdapter:
    """One-attempt lifecycle; all runtime I/O remains mock-only in this revision."""
    def __init__(self, transport):
        require(type(transport) in (MockTransport, BoundedTransport), "C2_MOCK_TRANSPORT_REQUIRED")
        self.transport = transport
        self.used = False

    def live(self, *args, **kwargs):
        launch_live(*args, **kwargs)

    def run_components(self, collector, archive, approval, limits, diagnostics, monitor=None):
        """Dormant lifecycle using bounded components; no entrypoint invokes it.

        Concrete transport/archive/collector/evidence backends are locked. Tests
        supply memory-only dependencies. No signal or cleanup is automatic.
        """
        phase, attempted, complete = 'preflight', False, False
        require(type(self.transport) is BoundedTransport, 'BOUNDED_TRANSPORT_REQUIRED')
        try:
            require(not self.used, 'RETRY_DISABLED')
            self.used = True
            check_immutable()
            state = collector.collect()
            comparator = NodeComparator(self.transport)
            before = comparator.compare('production', self.transport.call('production', production_sql().encode()))
            require(before['fingerprints'] == FINGERPRINTS, 'PRODUCTION_BASELINE')
            state['productionFingerprints'] = before['fingerprints']
            preflight(state, dict(path=ARCHIVE,exists=True,sha256=ARCHIVE_SHA,bytes=1608294,
                regular=True,symlink=False,uid=0,gid=0,mode='0600',format='CUSTOM'), approval, limits)
            require(archive.expected_sha == ARCHIVE_SHA and archive.expected_size == 1608294, 'ARCHIVE')
            archive.check()
            monitor = ConcurrentMonitor(collector.resource_sample, limits) if monitor is None else monitor
            monitor.start()
            phase = 'creation'
            monitor.check()
            self.transport.call('createdb',timeout=min(20,limits['maximumRestoreSeconds']),stop=monitor.stop,watchdog=monitor.check)
            phase = 'restore'; attempted = True
            self.transport.call('restore',data=archive,timeout=limits['maximumRestoreSeconds'],maximum=MAX_DIAGNOSTIC,
                stop=monitor.stop,watchdog=monitor.check)
            complete = True
            phase = 'verification'
            monitor.check()
            target = comparator.compare('target',self.transport.call('target',(ROOT/'read-plan.sql').read_bytes(),watchdog=monitor.check))
            after = comparator.compare('production',self.transport.call('production',production_sql().encode(),watchdog=monitor.check))
            require(after['fingerprints'] == before['fingerprints'], 'PRODUCTION_CHANGED')
            observed = collector.collect(require_absent=False)
            require(observed['targetExists'] is True and observed['appStartedAt']==state['appStartedAt']
                    and observed['pgStartedAt']==state['pgStartedAt'], 'PRODUCTION_CHANGED')
            monitor.close();monitor=None
            archive.close()
            diagnostics.write('qualification-summary.json',diagnostic_record('COMPARATOR_PASS',phase,'VERIFIED'))
            return {'status':'COMPONENT_PASS','fingerprints':target['fingerprints'],'commitOutcome':'VERIFIED',
                    'retry':False,'fallback':False,'cleanup':False,'restart':False,'qualified':False}
        except Exception as error:
            # No inference of commit or server cessation from a child/process error.
            lost = type(error) is SafetyStop and str(error) in {'PROCESS_IO_FAILURE','PROCESS_TIMEOUT','PROCESS_STDIN','MONITOR_STOP'}
            record=diagnostic_record('PROCESS_FAILED',phase,commit_outcome(attempted,complete,False,lost or not complete))
            try:
                diagnostics.write('qualification-failure.json',record)
            except Exception:
                record['evidenceFailure']=True
            record.update(status='STOP',retain=True,cessationConfirmed=False)
            return record
        finally:
            if monitor is not None:
                try:monitor.close()
                except Exception:pass
            try:archive.close()
            except Exception:pass

    def run_mock(self, state, archive, approval, limits, samples, postflight):
        trace = []
        creation_attempted = False
        restore_attempted = False
        try:
            require(not self.used, "RETRY_DISABLED")
            self.used = True
            preflight(state, archive, approval, limits)
            require(type(samples) is list and len(samples) > 0, "MONITOR_MISSING")
            require(samples[0].get("elapsedSeconds") == 0, "MONITOR_START")
            previous = monitor_sample(samples[0], 0, limits)
            trace.append("mock_monitor_started")
            creation_attempted = True
            result = self.transport.command("createdb", fixed_command("createdb", TARGET, CLUSTER), process_environment())
            require(result.get("returncode") == 0, "CREATION_FAILED")
            trace.append("mock_created")
            restore_attempted = True
            result = self.transport.command("restore", fixed_command("restore", TARGET, CLUSTER), process_environment())
            # Samples model independent observations while restore is in progress.
            for sample in samples[1:]:
                previous = monitor_sample(sample, previous, limits)
            require(len(samples) >= 2, "MONITOR_MISSING")
            require(result.get("connectionLost") is not True, "COMMIT_OUTCOME_UNCERTAIN")
            require(result.get("returncode") == 0, "RESTORE_FAILED")
            trace.append("mock_restored")
            # Comparator result is supplied by a mock. Never reimplement Node hashes.
            require(postflight.get("status") == "PASS" and postflight.get("readOnly") is True
                    and postflight.get("fingerprints") == FINGERPRINTS
                    and postflight.get("supplemental") is True, "VERIFICATION_FAILED")
            require(postflight.get("productionFingerprints") == state["productionFingerprints"]
                    and postflight.get("configUnchanged") is True
                    and postflight.get("startTimesUnchanged") is True
                    and postflight.get("healthy") is True
                    and postflight.get("targetAppSessions") == 0, "PRODUCTION_CHANGED")
            return {"status": "MOCK_PASS", "trace": trace, "qualified": False,
                    "retry": False, "fallback": False, "cleanup": False, "realCommands": 0}
        except Exception as error:
            # Drop arbitrary exception/process output rather than regex-redacting it.
            allowed = {"RETRY_DISABLED", "LIMITS", "OWNER_APPROVAL", "IDENTITY", "TARGET", "TARGET_EXISTS",
                "ARCHIVE", "ARCHIVE_MISSING", "ARCHIVE_PROPERTIES", "VERSION", "ADMIN_IDENTITY",
                "APPLICATION_TARGET", "HEALTH_OR_MAINTENANCE", "PERMISSIONS", "WINDOW", "CAPACITY",
                "PRODUCTION_BASELINE", "PREFLIGHT_BOUNDARY", "MONITOR_MISSING", "MONITOR_START",
                "MONITOR_SAMPLE", "MONITOR_HEALTH", "MONITOR_GAP", "MONITOR_DURATION", "MONITOR_CAPACITY",
                "MONITOR_PRESSURE", "CREATION_FAILED", "RESTORE_FAILED", "COMMIT_OUTCOME_UNCERTAIN",
                "VERIFICATION_FAILED", "PRODUCTION_CHANGED"}
            code = str(error) if type(error) is SafetyStop and str(error) in allowed else "TRANSPORT_OR_INPUT_FAILURE"
            return {"status": "MOCK_STOP", "code": code, "trace": trace,
                    "targetMayRemain": creation_attempted, "commitOutcome": "UNKNOWN" if restore_attempted else "NOT_ATTEMPTED",
                    "cessationConfirmed": False, "retain": True, "retry": False, "fallback": False,
                    "cleanup": False, "realCommands": 0}


def c2_self_test():
    import copy
    tests = []
    def check(name, value):
        require(value, "C2_SELF_TEST")
        tests.append(name)
    def rejects(name, action):
        try:
            action()
        except SafetyStop:
            tests.append(name)
        else:
            raise SafetyStop("C2_SELF_TEST")
    limits = dict(minimumFreeBytes=100, minimumAvailableMemoryBytes=100, maximumRestoreSeconds=10,
                  monitorIntervalSeconds=1, maximumCpuPercent=90, maximumWalBytes=100, maximumLockSeconds=2)
    state = dict(container=CONTAINER, image=IMAGE, cluster=CLUSTER, target=TARGET, targetExists=False,
                 archiveSHA256=ARCHIVE_SHA, version="16.15", clientVersion="16.15", adminDatabase="postgres",
                 adminUser="vps_pg_admin", appTarget="alrifai", healthy=True, conflictingMaintenance=False,
                 permissionsOK=True, windowOK=True, freeBytes=1000, availableMemoryBytes=1000,
                 productionFingerprints=FINGERPRINTS.copy(), configUnchanged=True, targetSessions=0)
    archive = dict(path=ARCHIVE, exists=True, sha256=ARCHIVE_SHA, bytes=1608294,
                   regular=True, symlink=False, uid=0, gid=0, mode="0600", format="CUSTOM")
    approval = dict(stage="C", target=TARGET, cluster=CLUSTER, archiveSHA256=ARCHIVE_SHA,
                    actions=["create", "restore", "verify"], signals=[])
    sample = dict(elapsedSeconds=0, freeBytes=1000, availableMemoryBytes=1000,
                  cpuPercent=1, walBytes=0, lockSeconds=0, healthy=True)
    samples = [sample, {**sample, "elapsedSeconds": 1}]
    post = dict(status="PASS", readOnly=True, fingerprints=FINGERPRINTS.copy(), supplemental=True,
                productionFingerprints=FINGERPRINTS.copy(), configUnchanged=True,
                startTimesUnchanged=True, healthy=True, targetAppSessions=0)
    def run(st=None, ar=None, ap=None, li=None, sa=None, po=None, outcomes=None):
        transport = MockTransport(outcomes)
        result = FixedTargetAdapter(transport).run_mock(state if st is None else st,
            archive if ar is None else ar, approval if ap is None else ap, limits if li is None else li,
            samples if sa is None else sa, post if po is None else po)
        return result, transport
    check("C2 mock lifecycle", run()[0]["status"] == "MOCK_PASS")
    for key, value in [("target", "alrifai"), ("target", "wrong"), ("cluster", "wrong"),
                       ("targetExists", True), ("targetSessions", 1), ("clientVersion", "wrong"),
                       ("configUnchanged", False), ("appTarget", TARGET)]:
        result, transport = run(st={**state, key:value})
        check("C2 preflight " + key + ':' + str(value), result["status"] == "MOCK_STOP" and not transport.calls)
    for key, value in [("exists", False), ("sha256", "altered"), ("path", "/tmp/other"), ("bytes", 0),
                       ("symlink", True), ("uid", 1), ("gid", 1), ("mode", "0644"), ("format", "PLAIN")]:
        result, transport = run(ar={**archive,key:value})
        check("C2 archive " + key, result["status"] == "MOCK_STOP" and not transport.calls)
    for ap in [{}, {**approval,"stage":"C2"}, {**approval,"cluster":"wrong"}, {**approval,"actions":[]}]:
        result, transport = run(ap=ap)
        check("C2 missing/invalid execution approval", result["status"] == "MOCK_STOP" and not transport.calls)
    for operation in ["createdb", "restore"]:
        for outcome in [{"returncode":1,"stderr":"PRIVATE_SENTINEL"}, RuntimeError("PRIVATE_SENTINEL")]:
            result, transport = run(outcomes={operation:outcome})
            check("C2 failure " + operation, result["status"] == "MOCK_STOP" and
                  transport.calls.count(operation) == 1 and "PRIVATE_SENTINEL" not in json.dumps(result)
                  and not result["retry"] and not result["fallback"] and not result["cleanup"])
    result, _ = run(outcomes={"restore":{"returncode":0,"connectionLost":True}})
    check("C2 disconnect near commit", result["code"] == "COMMIT_OUTCOME_UNCERTAIN" and result["commitOutcome"] == "UNKNOWN")
    for key, value in [("freeBytes",0),("availableMemoryBytes",0),("cpuPercent",91),
                       ("walBytes",101),("lockSeconds",3),("healthy",False),
                       ("elapsedSeconds",11),("elapsedSeconds",2),("cpuPercent",float('nan'))]:
        result, _ = run(sa=[sample,{**sample,"elapsedSeconds":1,key:value}])
        check("C2 monitor " + key + ':' + str(value), result["status"] == "MOCK_STOP" and not result["cessationConfirmed"])
    for sa in [[], [sample], [{**sample,"elapsedSeconds":1}]]:
        check("C2 missing monitor", run(sa=sa)[0]["status"] == "MOCK_STOP")
    for value in [float('nan'),float('inf'),True,0,-1]:
        rejects("C2 invalid numeric limit", lambda v=value:validate_limits({**limits,"maximumRestoreSeconds":v}))
    for key, value in [("status","FAIL"),("fingerprints",{}),("supplemental",False),
                       ("productionFingerprints",{}),("startTimesUnchanged",False),("targetAppSessions",1)]:
        check("C2 postflight " + key, run(po={**post,key:value})[0]["status"] == "MOCK_STOP")
    for operation in ["createdb", "restore"]:
        argv = fixed_command(operation,TARGET,CLUSTER)
        rejects("C2 argv injection", lambda:validate_command(operation,argv+["--clean"],TARGET,CLUSTER,process_environment()))
        rejects("C2 environment injection", lambda:validate_command(operation,argv,TARGET,CLUSTER,{**process_environment(),"PGDATABASE":"alrifai"}))
    check("C2 exact environment", set(process_environment()) == {"PATH","LANG","LC_ALL","TZ"})
    transport = MockTransport(); adapter = FixedTargetAdapter(transport)
    adapter.run_mock(state,archive,approval,limits,samples,post)
    check("C2 no retry", adapter.run_mock(state,archive,approval,limits,samples,post)["code"] == "RETRY_DISABLED" and len(transport.calls) == 2)
    rejects("C2 arbitrary transport blocked", lambda:FixedTargetAdapter(object()))
    # Even a fabricated full approval and a modified legacy flag cannot open OS transport.
    global LIVE_EXECUTION_ENABLED
    old = LIVE_EXECUTION_ENABLED
    try:
        LIVE_EXECUTION_ENABLED = True
        rejects("C2 fabricated approval cannot launch", lambda:launch_live(approval=approval))
        rejects("C2 adapter live locked", lambda:adapter.live(approval=approval))
    finally:
        LIVE_EXECUTION_ENABLED = old
    session = dict(database=TARGET,applicationName=APP_NAME,user="vps_pg_admin",backendType="client backend",
                   clientAddress=None,pid=123,backendStart="2026-10-08T06:00:00Z")
    cap = dict(pid=123,backendStart=session["backendStart"])
    window = ("2026-10-08T05:59:00Z","2026-10-08T06:01:00Z")
    for action in ["cancel","terminate"]:
        rejects("C2 unauthorized " + action, lambda a=action:cancellation_request(a,approval,CLUSTER,[session],cap,window))
        ap = {**approval,"signals":[action]}
        check("C2 authorized mock " + action, cancellation_request(action,ap,CLUSTER,[session],cap,window)["action"] == 'MOCK_'+action.upper())
        for ss, cp in [([session,session],cap),([],cap),([session],{**cap,"pid":124}),
                       ([session],{**cap,"backendStart":"2026-10-08T06:00:01Z"}),([{**session,"database":"alrifai"}],cap)]:
            rejects("C2 exact-session " + action, lambda a=action,s=ss,c=cp:cancellation_request(a,ap,CLUSTER,s,c,window))
    return {"status":"PASS","tests":len(tests),"cases":tests,"fixtures":"SYNTHETIC_ONLY",
            "realCommands":0,"databaseConnections":0,"signals":0,"qualified":False}


# C3 dormant components. Every concrete OS/filesystem boundary calls the
# unconditional lock. Offline tests inject memory-only backends instead.
ROOT = Path(__file__).resolve().parent
NODE = "/root/.vscode-server/cli/servers/Stable-07f806f999227108933c2e30515b26eecc1fda74/server/node"
IMMUTABLE = {
    "verifier.mjs": "84c005c753a0cd0cf749fdabe9110dd519a0b010e21e35ba1076592306247a79",
    "read-plan.sql": "d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749",
    "evidence-readonly.mjs": "10737d01e38c194e5770b5419323f26795f8bf55ede4d15de8d0fe25d31c34be",
    "baseline-attestation.json": "436d0029fc078042f9ac88e4802483e654445cae4f60022766a047cc7ed99b05",
    "baseline-catalog.json": "b5e3d64c2124b0c2b3fdac772f0a129165c10ecb72cd4d938620f954c4dd2394",
}
MAX_FRAMES = 64 * 1024 * 1024
MAX_DIAGNOSTIC = 64 * 1024


def check_immutable():
    for name, digest in IMMUTABLE.items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, "IMMUTABLE_CHANGED")


def psql_argv(database, readonly=True):
    require(database in ("postgres", "alrifai", TARGET), "DATABASE")
    require(readonly is True, "READ_ONLY_REQUIRED")
    # env -i also clears inherited container PG* settings. Fixed absolute binary
    # paths and env availability must be qualified before integration.
    return ["/usr/bin/docker", "exec", "-i", CONTAINER, "/usr/bin/env", "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C", "TZ=UTC",
            "PGOPTIONS=-c default_transaction_read_only=on -c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000",
            "/usr/local/bin/psql", "-X", "-qAt", "-w", "-h", "/var/run/postgresql",
            "-p", "5432", "-U", "vps_pg_admin", "-d", database, "-v", "ON_ERROR_STOP=1"]


def restore_argv(operation):
    original = fixed_command(operation, TARGET, CLUSTER)
    # Reuse the C2 restore/create flags, replace only execution prefix/env.
    index = original.index("createdb" if operation == "createdb" else "pg_restore")
    suffix = original[index + 1:]
    return ["/usr/bin/docker", "exec"] + (["-i"] if operation == "restore" else []) + [
        CONTAINER, "/usr/bin/env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C", "TZ=UTC",
        "PGAPPNAME=" + APP_NAME, "/usr/local/bin/" + original[index]] + suffix


def guarded_sql(database, body):
    require(database in ("postgres", "alrifai", TARGET), "DATABASE")
    return ("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
            "SET LOCAL search_path=public; SET LOCAL timezone='UTC';\n"
            "SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='5s';\n"
            "SELECT current_database()='" + database + "' AND current_user='vps_pg_admin' "
            "AND current_setting('transaction_read_only')='on' "
            "AND current_setting('server_version')='16.15' "
            "AND (SELECT system_identifier::text FROM pg_control_system())='" + CLUSTER + "' AS observation_guard \\gset\n"
            "\\if :observation_guard\n" + body + "\nROLLBACK;\n\\else\nROLLBACK;\n\\quit 3\n\\endif\n")


def observation_sql():
    body = """SELECT json_build_object(
 'database',current_database(),'user',current_user,'cluster',(SELECT system_identifier::text FROM pg_control_system()),
 'version',current_setting('server_version'),'readOnly',current_setting('transaction_read_only'),
 'targetExists',EXISTS(SELECT 1 FROM pg_database WHERE datname='alrifai_restore_20261008_053528'),
 'targetSessions',(SELECT count(*) FROM pg_stat_activity WHERE datname='alrifai_restore_20261008_053528'),
 'appTargets',COALESCE((SELECT json_agg(DISTINCT datname) FROM pg_stat_activity WHERE usename='alrifai_app'),'[]'::json));"""
    return guarded_sql("postgres", body)


def production_sql():
    # Separate production-only plan. The original qualification guard is never
    # rewritten or executed against production. Only fixed projection text is reused.
    check_immutable()
    sql = (ROOT / "read-plan.sql").read_text()
    projections = sql.split("\\if :qualification_guard\n", 1)[1].split("\nROLLBACK;", 1)[0]
    return guarded_sql("alrifai", projections)


def resource_sql():
    return guarded_sql("postgres", """SELECT json_build_object(
 'cluster',(SELECT system_identifier::text FROM pg_control_system()),
 'walBytes',(SELECT COALESCE(sum(size),0) FROM pg_ls_waldir()),
 'lockSeconds',COALESCE((SELECT max(EXTRACT(EPOCH FROM clock_timestamp()-query_start))
 FROM pg_stat_activity WHERE wait_event_type='Lock' AND state='active'),0),
 'sessions',COALESCE((SELECT json_agg(json_build_object('database',datname,'applicationName',application_name,
 'user',usename,'backendType',backend_type,'clientAddress',client_addr,'pid',pid,'backendStart',backend_start))
 FROM pg_stat_activity WHERE datname='alrifai_restore_20261008_053528'),'[]'::json));""")


class OSProcess:
    """Nonblocking pipe wrapper. Constructible only after the locked OS boundary."""
    def __init__(self, child):
        self.child = child
        self.input_closed = False
        self.eof = {"stdout": False, "stderr": False}
        for stream in (child.stdin, child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)

    def write(self, data):
        try:
            return os.write(self.child.stdin.fileno(), data)
        except BlockingIOError:
            return 0

    def close_input(self):
        if not self.input_closed:
            self.child.stdin.close()
            self.input_closed = True

    def read(self, stream):
        if self.eof[stream]:
            return b""
        try:
            data = os.read(getattr(self.child, stream).fileno(), 65536)
            if not data:
                self.eof[stream] = True
            return data
        except BlockingIOError:
            return b""

    def poll(self):
        return self.child.poll()

    def drained(self):
        return all(self.eof.values())

    def detach(self):
        # Never signal/kill/retry here. Closing client pipes is not server cessation.
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            try:
                stream.close()
            except OSError:
                pass


class LockedOSBackend:
    def spawn(self, argv, environment):
        launch_live()
        # Dormant actual implementation: unreachable while launch_live is locked.
        import subprocess
        return OSProcess(subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=environment, shell=False, close_fds=True))


class BoundedTransport:
    """Pumps fixed operations; backend injection supports memory-only testing."""
    def __init__(self, backend=None, clock=time.monotonic, pause=time.sleep):
        self.backend = LockedOSBackend() if backend is None else backend
        self.clock, self.pause = clock, pause

    def call(self, operation, data=b"", timeout=20, maximum=MAX_FRAMES, stop=None, watchdog=None):
        require(finite_number(timeout) and 0 < timeout <= 3600, "PROCESS_LIMIT")
        require(type(maximum) is int and 0 < maximum <= MAX_FRAMES, "PROCESS_LIMIT")
        commands = {"identity": psql_argv("postgres"), "resources": psql_argv("postgres"),
                    "target": psql_argv(TARGET), "production": psql_argv("alrifai"),
                    "createdb": restore_argv("createdb"), "restore": restore_argv("restore"),
                    "compare": [NODE, "--input-type=module", "-e", NODE_BRIDGE],
                    "inspect-pg": ["/usr/bin/docker", "inspect", "--format", "{{json .}}", CONTAINER],
                    "inspect-app": ["/usr/bin/docker", "inspect", "--format", "{{json .}}", "al-rifai-app-1"],
                    "version": ["/usr/bin/docker", "exec", CONTAINER, "/usr/local/bin/psql", "--version"]}
        require(operation in commands, "COMMAND")
        require(type(data) is bytes or isinstance(data, ArchiveDescriptor), "PROCESS_INPUT")
        return self._pump(commands[operation], data, timeout, maximum, stop, watchdog)

    def _pump(self, argv, data, timeout, maximum, stop=None, watchdog=None, early=False):
        child = None
        try:
            child = self.backend.spawn(argv, process_environment())
            started = self.clock()
            output = bytearray()
            errors = 0
            offset = 0
            pending = b""
            input_done = False
            while True:
                require(self.clock() - started <= timeout, "PROCESS_TIMEOUT")
                require(stop is None or not stop.is_set(), "MONITOR_STOP")
                if watchdog is not None:
                    watchdog()
                if not input_done:
                    if not pending:
                        if type(data) is bytes:
                            pending = data[offset:offset + 65536]
                        else:
                            pending = data.read(65536)
                        if not pending:
                            child.close_input()
                            input_done = True
                    if pending:
                        try:
                            sent = child.write(pending)
                        except BrokenPipeError:
                            require(early, "PROCESS_IO_FAILURE")
                            child.close_input(); input_done = True; pending = b""
                            sent = 0
                        require(type(sent) is int and 0 <= sent <= len(pending), "PROCESS_STDIN")
                        offset += sent
                        pending = pending[sent:]
                chunk = child.read("stdout")
                require(type(chunk) is bytes, "PROCESS_OUTPUT")
                output.extend(chunk)
                errors += len(child.read("stderr"))
                require(len(output) <= maximum and errors <= MAX_DIAGNOSTIC, "PROCESS_OUTPUT_OVERFLOW")
                code = child.poll()
                if code is not None and child.drained():
                    require(input_done or early, "PROCESS_STDIN")
                    require(code == 0, "PROCESS_FAILED")
                    if isinstance(data, ArchiveDescriptor):
                        if early: data.check()
                        else: data.finish()
                    return bytes(output)
                self.pause(0.005)
        except SafetyStop:
            raise
        except Exception:
            raise SafetyStop("PROCESS_IO_FAILURE") from None
        finally:
            if child is not None:
                child.detach()


def secure_archive_open(path):
    require(path == ARCHIVE, 'ARCHIVE')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in Path(path).parent.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent); parent = nxt
            info = os.fstat(parent)
            require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) & 0o022 == 0, 'ARCHIVE_PARENT')
        return os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)

class LockedArchiveFS:
    def open(self, path):
        launch_live()
        return secure_archive_open(path)

    def metadata(self, fd):
        value = os.fstat(fd)
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                value.st_ctime_ns, value.st_uid, value.st_gid, value.st_mode)

    def read(self, fd, size):
        return os.read(fd, size)

    def rewind(self, fd):
        os.lseek(fd, 0, os.SEEK_SET)

    def close(self, fd):
        os.close(fd)


class ArchiveDescriptor:
    """Hash and stream the same protected descriptor; check drift per chunk."""
    def __init__(self, fs=None, expected_sha=ARCHIVE_SHA, expected_size=1608294):
        self.fs = LockedArchiveFS() if fs is None else fs
        self.fd = None
        # Alternate expected values are allowed only for an explicitly injected FS.
        require(fs is not None or (expected_sha == ARCHIVE_SHA and expected_size == 1608294), "ARCHIVE")
        self.expected_sha, self.expected_size = expected_sha, expected_size
        try:
            self.fd = self.fs.open(ARCHIVE)
            self.initial = self.fs.metadata(self.fd)
            _, _, size, _, _, uid, gid, mode = self.initial
            require(size == expected_size and uid == gid == 0 and stat.S_ISREG(mode)
                    and stat.S_IMODE(mode) == 0o600, "ARCHIVE_PROPERTIES")
            digest, count, header = hashlib.sha256(), 0, b""
            while True:
                data = self.fs.read(self.fd, 65536)
                if not data:
                    break
                if not header:
                    header = data[:5]
                count += len(data)
                require(count <= expected_size, "ARCHIVE_SIZE")
                digest.update(data)
            require(header == b"PGDMP" and count == expected_size and digest.hexdigest() == expected_sha, "ARCHIVE_CHECKSUM")
            self.check()
            self.fs.rewind(self.fd)
            self.stream_hash, self.stream_bytes = hashlib.sha256(), 0
        except Exception:
            self.close()
            raise SafetyStop("ARCHIVE_VALIDATION_FAILED") from None

    def check(self):
        require(self.fd is not None and self.fs.metadata(self.fd) == self.initial, "ARCHIVE_DRIFT")

    def read(self, size):
        self.check()
        data = self.fs.read(self.fd, size)
        self.stream_hash.update(data)
        self.stream_bytes += len(data)
        require(self.stream_bytes <= self.expected_size, "ARCHIVE_SIZE")
        return data

    def finish(self):
        self.check()
        require(self.stream_bytes == self.expected_size and
                self.stream_hash.hexdigest() == self.expected_sha, "ARCHIVE_STREAM_CHECKSUM")

    def close(self):
        if self.fd is not None:
            self.fs.close(self.fd)
            self.fd = None


class LockedObservations:
    """Dormant OS collector; raw inspections/config remain private in memory."""
    def __init__(self, transport, reference, window):
        self.transport, self.reference, self.window = transport, reference, window
        self.previous_cpu = None
        self.resource_lock = threading.Lock()

    def collect(self):
        launch_live()
        return host_observation_collect(self)

    def resources(self):
        launch_live()
        return host_observation_resources(self)

    def warmup(self):
        launch_live()
        cpu=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        self.previous_cpu=(sum(cpu),cpu[3]+cpu[4])


def host_observation_collect(self):
    pg = json.loads(self.transport.call("inspect-pg", maximum=MAX_DIAGNOSTIC))
    app = json.loads(self.transport.call("inspect-app", maximum=MAX_DIAGNOSTIC))
    version = self.transport.call("version", maximum=1024).decode().strip()
    # This fixed application source hardcodes alrifai. Hash/config observations
    # must match independently reviewed reference values; no pool is imported.
    source = Path('/opt/vps/apps/al-rifai/db/postgres.mjs').read_bytes()
    configuration = Path('/etc/vps/apps/al-rifai/app.env').read_bytes()
    mounts = app.get('Mounts', [])
    environment = app.get('Config', {}).get('Env', [])
    source_sha = hashlib.sha256(source).hexdigest()
    config_sha = hashlib.sha256(configuration).hexdigest()
    require(b"database:'alrifai'" in source, "APPLICATION_TARGET")
    require(not any(x.startswith('PGDATABASE=') and x != 'PGDATABASE=alrifai' for x in environment), "APPLICATION_TARGET")
    now = datetime.datetime.now(datetime.timezone.utc)
    begin, end = [datetime.datetime.fromisoformat(t.replace('Z','+00:00')) for t in self.window]
    require(begin.tzinfo is not None and end.tzinfo is not None, "WINDOW")
    healthy = all(x.get('State', {}).get('Running') is True and
                  x.get('State', {}).get('Health', {}).get('Status') == 'healthy' for x in [pg,app])
    if self.previous_cpu is None:
        self.warmup()
        time.sleep(0.02)
    resources = self.resources()
    return dict(container=pg.get('Id'), image=pg.get('Image'), appTarget='alrifai', healthy=healthy,
        permissionsOK=stat.S_IMODE(ROOT.stat().st_mode)==0o750 and ROOT.stat().st_uid==0,
        conflictingMaintenance=self.reference.get('maintenanceCleared') is not True,
        configUnchanged=source_sha==self.reference.get('applicationSourceSHA256') and
            config_sha==self.reference.get('applicationConfigSHA256') and
            hashlib.sha256(json.dumps(mounts,sort_keys=True).encode()).hexdigest()==self.reference.get('mountsSHA256'),
        windowOK=begin<=now<=end, clientVersion='16.15' if version.endswith('16.15') else 'UNKNOWN',
        appStartedAt=app.get('State',{}).get('StartedAt'), pgStartedAt=pg.get('State',{}).get('StartedAt'),
        freeBytes=resources['freeBytes'], availableMemoryBytes=resources['availableMemoryBytes'])

def host_observation_resources(self):
    with self.resource_lock:
        return host_resource_acquisition(self)

def host_resource_acquisition(self):
    disk = os.statvfs('/var/lib/vps/postgres')
    fields = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    memory = int(fields['MemAvailable'].strip().split()[0])*1024
    cpu = list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    total, idle = sum(cpu), cpu[3]+cpu[4]
    require(self.previous_cpu is not None, "CPU_WARMUP_REQUIRED")
    previous_total, previous_idle = self.previous_cpu
    self.previous_cpu = (total,idle)
    require(total>previous_total, "CPU_SAMPLE_INVALID")
    percent = 100*(1-(idle-previous_idle)/(total-previous_total))
    # Live health cannot be inferred from process existence; inspect boundedly.
    pg = json.loads(self.transport.call('inspect-pg',maximum=MAX_DIAGNOSTIC))
    app = json.loads(self.transport.call('inspect-app',maximum=MAX_DIAGNOSTIC))
    healthy = all(x.get('State',{}).get('Running') is True and x.get('State',{}).get('Health',{}).get('Status')=='healthy' for x in [pg,app])
    return dict(freeBytes=disk.f_bavail*disk.f_frsize,availableMemoryBytes=memory,cpuPercent=percent,healthy=healthy)

class PreflightCollector:
    def __init__(self, transport, observations=None):
        self.transport = transport
        self.observations = LockedObservations(transport, {}, ()) if observations is None else observations

    def collect(self, require_absent=True):
        try:
            actual = json.loads(self.transport.call("identity", observation_sql().encode(), maximum=MAX_DIAGNOSTIC))
            require(actual.get("database") == "postgres" and actual.get("user") == "vps_pg_admin"
                    and actual.get("cluster") == CLUSTER and actual.get("version") == "16.15"
                    and actual.get("readOnly") == "on", "PREFLIGHT_IDENTITY")
            require(type(actual.get("targetExists")) is bool and (not require_absent or actual["targetExists"] is False)
                    and actual.get("targetSessions") == 0, "TARGET_EXISTS")
            require(type(actual.get("appTargets")) is list and
                    all(x == "alrifai" for x in actual["appTargets"]), "APPLICATION_TARGET")
            observed = self.observations.collect()
            require(observed.get("container") == CONTAINER and observed.get("image") == IMAGE
                    and observed.get("appTarget") == "alrifai" and observed.get("healthy") is True
                    and observed.get("permissionsOK") is True and observed.get("conflictingMaintenance") is False
                    and observed.get("configUnchanged") is True and observed.get("windowOK") is True
                    and observed.get("clientVersion") == "16.15", "PREFLIGHT_OBSERVATIONS")
            # An idle app is allowed only because its actual config is independently checked.
            return {**observed, "cluster": actual["cluster"], "version": actual["version"],
                    "target": TARGET, "targetExists": actual["targetExists"], "targetSessions": actual["targetSessions"],
                    "adminDatabase": "postgres", "adminUser": actual["user"], "archiveSHA256": ARCHIVE_SHA}
        except SafetyStop:
            raise
        except Exception:
            raise SafetyStop("PREFLIGHT_INPUT") from None

    def resource_sample(self, elapsed):
        actual = json.loads(self.transport.call("resources", resource_sql().encode(), maximum=MAX_DIAGNOSTIC))
        require(actual.get("cluster") == CLUSTER, "MONITOR_IDENTITY")
        require(type(actual.get('sessions')) is list and all(type(row) is dict and
                {'database','applicationName','user','backendType','clientAddress','pid','backendStart'}.issubset(row)
                for row in actual['sessions']), 'MONITOR_SESSIONS')
        sample = self.observations.resources()
        return {**sample, "elapsedSeconds": elapsed, "walBytes": actual["walBytes"], "lockSeconds": actual["lockSeconds"],
                "restoreSessions": actual.get("sessions", [])}


class ConcurrentMonitor:
    def __init__(self, collector, limits, clock=time.monotonic, timing=None):
        validate_limits(limits)
        self.collector, self.limits, self.clock = collector, limits, clock
        self.timing = timing
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.shutdown = threading.Event()
        self.last = None
        self.failure = None
        self.thread = None
        self.started = None

    def start(self):
        require(self.thread is None, "MONITOR_RESTART_DISABLED")
        self.started = self.clock()
        def worker():
            previous = 0
            try:
                while not self.shutdown.is_set():
                    elapsed = self.clock() - self.started
                    acquisition_start = self.clock()
                    sample = self.collector(elapsed)
                    if self.timing is not None:
                        require(self.clock() - acquisition_start <= self.timing['acquisitionSeconds'], 'MONITOR_ACQUISITION_AGE')
                    previous = monitor_sample(sample, previous, self.limits)
                    self.last = acquisition_start if self.timing is not None else self.clock()
                    self.ready.set()
                    self.shutdown.wait(self.limits["monitorIntervalSeconds"] / 2)
            except Exception:
                self.failure = "MONITOR_FAILED"
                self.stop.set()
                self.ready.set()
        self.thread = threading.Thread(target=worker, daemon=True, name="recovery-monitor")
        self.thread.start()
        require(self.ready.wait(self.timing["startupSeconds"] if self.timing is not None else min(1, self.limits["monitorIntervalSeconds"])), "MONITOR_START_TIMEOUT")
        self.check()

    def check(self):
        try:
            require(self.thread is not None and self.thread.is_alive() and not self.stop.is_set()
                    and self.last is not None, "MONITOR_FAILED")
            require(self.clock() - self.last <= (self.timing["freshnessSeconds"] if self.timing is not None else self.limits["monitorIntervalSeconds"]), "MONITOR_STALE")
            require(self.clock() - self.started <= self.limits["maximumRestoreSeconds"], "MONITOR_DURATION")
        except SafetyStop:
            self.stop.set()
            raise

    def close(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=1)
        require(self.thread is None or not self.thread.is_alive(), "MONITOR_CLOSE_TIMEOUT")


NODE_BRIDGE = r"""
import {readFileSync} from 'node:fs';
import {decodeFrames,verifyCollected,fingerprints,TABLES,CATALOG_KEYS,assertSupplemental,TARGET,CLUSTER,ARCHIVE_SHA} from 'file:///opt/vps/infra/recovery/al-rifai/verifier.mjs';
import {readEvidenceSet,expectedSnapshots,assertExactSnapshots} from 'file:///opt/vps/infra/recovery/al-rifai/evidence-readonly.mjs';
export function comparePacket(p){
 const baseline=JSON.parse(readFileSync('/opt/vps/infra/recovery/al-rifai/baseline-attestation.json','utf8'));
 if(p.mode==='target'){
  const collected=decodeFrames(p.frames);
  const expected=expectedSnapshots(readEvidenceSet(baseline.evidence.directory,baseline.evidence.files));
  return verifyCollected({target:TARGET,cluster:CLUSTER,archiveSha:ARCHIVE_SHA},baseline,collected,expected);
 }
 if(p.mode!=='production')throw Error('MODE');
 const labels=['identity',...TABLES.map(t=>'table:'+t),...CATALOG_KEYS.map(k=>'catalog:'+k),'supplemental'];
 const fs=p.frames.trimEnd().split('\n').map(line=>JSON.parse(line));
 if(fs.length!==labels.length||fs.some((f,i)=>f.label!==labels[i]||!Array.isArray(f.rows)))throw Error('FRAMES');
 if(fs[0].rows.length!==1)throw Error('IDENTITY');
 const id=fs[0].rows[0];
 if(id.database!=='alrifai'||id.cluster!==CLUSTER||id.user!=='vps_pg_admin'||id.version!=='16.15'||id.readOnly!=='on')throw Error('IDENTITY');
 const rows=Object.fromEntries(TABLES.map((t,i)=>[t,fs[1+i].rows]));
 const catalog=Object.fromEntries(CATALOG_KEYS.map((k,i)=>[k,fs[1+TABLES.length+i].rows]));
 for(const r of rows.alrifai_schema_migrations){
  if(typeof r.applied_at!=='string'||!/^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(r.applied_at))throw Error('TIMESTAMP');
  r.applied_at=new Date(r.applied_at);if(!Number.isFinite(r.applied_at.valueOf()))throw Error('TIMESTAMP');
 }
 const last=fs.at(-1);if(last.rows.length!==1)throw Error('SUPPLEMENTAL');assertSupplemental(last.rows[0]);
 return {status:'OBSERVED',readOnly:true,fingerprints:fingerprints(rows,catalog)};
}
try {
 const bytes=readFileSync(0);if(bytes.length>64*1024*1024)throw Error('SIZE');
 const result=comparePacket(JSON.parse(bytes.toString('utf8')));
 console.log(JSON.stringify(result));
} catch {console.log(JSON.stringify({status:'BLOCKED',code:'COMPARATOR_FAILURE'}));process.exitCode=1;}
"""


class NodeComparator:
    def __init__(self, transport):
        self.transport = transport

    def compare(self, mode, frames):
        require(mode in ("target", "production") and type(frames) is bytes and len(frames) <= MAX_FRAMES // 2, "FRAME_LIMIT")
        check_immutable()
        try:
            packet = json.dumps({"mode": mode, "frames": frames.decode('utf8')}).encode()
            require(len(packet) <= MAX_FRAMES, "FRAME_LIMIT")
            result = json.loads(self.transport.call("compare", packet, maximum=MAX_DIAGNOSTIC))
            require(type(result) is dict and result.get("readOnly") is True and
                    result.get("status") == ("PASS" if mode == "target" else "OBSERVED"), "COMPARATOR_FAILURE")
            require(type(result.get("fingerprints")) is dict and set(result["fingerprints"]) == set(FINGERPRINTS)
                    and all(type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)
                            for v in result["fingerprints"].values()), "COMPARATOR_FAILURE")
            if mode == "target":
                require(result["fingerprints"] == FINGERPRINTS, "COMPARATOR_FAILURE")
            return {"status": result["status"], "readOnly": True, "fingerprints": result["fingerprints"]}
        except SafetyStop:
            raise
        except Exception:
            raise SafetyStop("COMPARATOR_FAILURE") from None


def signal_sql(action, matched):
    require(action in ("cancel", "terminate") and matched.get("database") == TARGET
            and matched.get("cluster") == CLUSTER and matched.get("applicationName") == APP_NAME, "SIGNAL_IDENTITY")
    pid = matched.get("pid")
    require(type(pid) is int and pid > 0, "CANCEL_PID")
    started = matched.get("backendStart")
    require(type(started) is str and all(c in '0123456789TZ:+-. ' for c in started), "CANCEL_TIMESTAMP")
    function = "pg_cancel_backend" if action == "cancel" else "pg_terminate_backend"
    # Identity is rechecked server-side. PID signaling still has residual reuse risk;
    # no atomic PID/backend-start API is claimed by this implementation.
    return guarded_sql("postgres", "SELECT " + function + "(pid) FROM pg_stat_activity WHERE "
        "datname='" + TARGET + "' AND application_name='" + APP_NAME + "' AND usename='vps_pg_admin' "
        "AND backend_type='client backend' AND client_addr IS NULL AND pid=" + str(pid) +
        " AND backend_start='" + started + "'::timestamptz "
        "AND (SELECT count(*) FROM pg_stat_activity WHERE datname='" + TARGET +
        "' AND application_name='" + APP_NAME + "')=1;")


def capture_restore_session(observation, window):
    require(observation.get('cluster') == CLUSTER, 'CANCEL_CLUSTER')
    sessions=observation.get('sessions')
    require(type(sessions) is list, 'CANCEL_AMBIGUOUS')
    candidates=[s for s in sessions if type(s) is dict and s.get('database')==TARGET and s.get('applicationName')==APP_NAME]
    require(len(candidates)==1,'CANCEL_AMBIGUOUS')
    captured={k:candidates[0].get(k) for k in ('pid','backendStart')}
    match_restore_session(CLUSTER,sessions,captured,window)
    return captured


class CancellationObserver:
    def __init__(self, observe, request_signal, clock=time.monotonic, pause=time.sleep):
        self.observe, self.request_signal, self.clock, self.pause = observe, request_signal, clock, pause

    def request(self, action, approval, captured, window, seconds):
        require(finite_number(seconds) and 0 < seconds <= 60, "CESSATION_LIMIT")
        observation = self.observe()
        matched = cancellation_request(action, approval, observation['cluster'], observation['sessions'], captured, window)
        # In production this callback must run the fixed statement in a locked
        # signal backend; a caller-supplied JSON record is never authorization.
        require(self.request_signal(signal_sql(action, matched)) is True, "SIGNAL_REJECTED")
        deadline = self.clock() + seconds
        while self.clock() <= deadline:
            observed = self.observe()
            require(observed.get('cluster') == CLUSTER, "CANCEL_CLUSTER")
            sessions = observed.get('sessions')
            require(type(sessions) is list, "CESSATION_INPUT")
            require(all(type(s) is dict and {'pid','backendStart','database','applicationName','user','backendType','clientAddress'}.issubset(s) for s in sessions), "CESSATION_INPUT")
            require(not any(s['pid'] == captured['pid'] and s['backendStart'] != captured['backendStart'] for s in sessions), "CANCEL_SESSION_CHANGED")
            if not any(s['pid'] == captured['pid'] and s['backendStart'] == captured['backendStart'] for s in sessions):
                require(not any(s['database']==TARGET and s['applicationName']==APP_NAME for s in sessions), 'CANCEL_SESSION_CHANGED')
                return {"status": "CESSATION_OBSERVED", "commitOutcome": "UNKNOWN", "qualified": False}
            self.pause(0.005)
        raise SafetyStop("CESSATION_TIMEOUT")


class LockedSignalBackend:
    def request(self, sql):
        launch_live()
        # A read-only transaction can call cancellation functions: signals are
        # side effects and require their own gate, despite SQL READ ONLY.
        import subprocess
        result = subprocess.run(psql_argv('postgres'), input=sql.encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=process_environment(),
            timeout=20, shell=False, check=False)
        return result.returncode == 0 and result.stdout.strip() == b't'


def commit_outcome(restore_attempted, process_complete, comparison_passed, connection_lost):
    if not restore_attempted:
        return "NOT_ATTEMPTED"
    if connection_lost or not process_complete:
        return "UNKNOWN"
    return "VERIFIED" if comparison_passed else "UNQUALIFIED"


class LockedEvidenceFS:
    def write_exclusive(self, name, data):
        launch_live()
        # Directory must already exist under separate owner approval; never mkdir.
        directory = '/var/lib/vps/al-rifai/recovery-evidence'
        fd = os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
        destination = None
        try:
            for part in directory.strip('/').split('/'):
                nxt = os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
                os.close(fd);fd=nxt
            info=os.fstat(fd)
            require(info.st_uid==info.st_gid==0 and stat.S_IMODE(info.st_mode)==0o700,'EVIDENCE_PERMISSIONS')
            destination=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd)
            view=memoryview(data)
            while view:
                sent=os.write(destination,view);require(sent>0,'EVIDENCE_IO');view=view[sent:]
            os.fsync(destination)
        finally:
            if destination is not None:os.close(destination)
            os.close(fd)


def diagnostic_record(code, phase, outcome):
    allowed_codes = {"COMPARATOR_PASS", "PROCESS_TIMEOUT", "PROCESS_FAILED", "PROCESS_IO_FAILURE", "PROCESS_OUTPUT_OVERFLOW",
                     "MONITOR_FAILED", "MONITOR_STALE", "COMPARATOR_FAILURE", "ARCHIVE_VALIDATION_FAILED"}
    allowed_phases = {"preflight", "creation", "restore", "verification", "stopped"}
    return {"code": code if type(code) is str and code in allowed_codes else "SUPPRESSED",
            "phase": phase if type(phase) is str and phase in allowed_phases else "SUPPRESSED",
            "commitOutcome": outcome if type(outcome) is str and outcome in {"UNKNOWN","NOT_ATTEMPTED","VERIFIED","UNQUALIFIED"} else "UNKNOWN",
            "retry": False, "fallback": False, "cleanup": False, "restart": False}


class DiagnosticEvidence:
    def __init__(self, fs=None):
        self.fs = LockedEvidenceFS() if fs is None else fs

    def write(self, name, record):
        require(name in ("qualification-summary.json", "qualification-failure.json"), "EVIDENCE_NAME")
        # Whitelist construction, not regex redaction of arbitrary data.
        safe = diagnostic_record(record.get('code'), record.get('phase'), record.get('commitOutcome'))
        data = json.dumps(safe, separators=(',', ':')).encode()
        require(len(data) <= MAX_DIAGNOSTIC, "EVIDENCE_SIZE")
        try:
            self.fs.write_exclusive(name, data)
        except Exception:
            raise SafetyStop("EVIDENCE_WRITE_FAILED") from None
        return safe



class SyntheticClock:
    def __init__(self): self.value=0
    def now(self): return self.value
    def pause(self, seconds): self.value+=seconds

class SyntheticProcess:
    def __init__(self, output=b'', error=b'', blocked=False, broken=False, code=0):
        self.output,self.error=bytearray(output),bytearray(error)
        self.blocked,self.broken,self.code=blocked,broken,code
        self.closed=False;self.detached=False;self.input=bytearray()
    def write(self,data):
        if self.broken:raise BrokenPipeError('PRIVATE_SENTINEL')
        if self.blocked:return 0
        self.input.extend(data);return len(data)
    def close_input(self):self.closed=True
    def read(self,stream):
        source=self.output if stream=='stdout' else self.error
        data=bytes(source[:65536]);del source[:65536];return data
    def poll(self):return self.code if self.closed and not self.blocked else None
    def drained(self):return not self.output and not self.error
    def detach(self):self.detached=True

class SyntheticBackend:
    def __init__(self,child=None,fail=False):self.child=child or SyntheticProcess();self.fail=fail;self.calls=[]
    def spawn(self,argv,environment):
        self.calls.append((argv,environment))
        if self.fail:raise OSError('PRIVATE_SENTINEL')
        return self.child

class SyntheticArchiveFS:
    def __init__(self,data,symlink=False):
        self.data=data;self.offset=0;self.symlink=symlink;self.closed=False
        self.meta=(1,2,len(data),3,4,0,0,stat.S_IFREG|0o600)
    def open(self,path):
        require(path==ARCHIVE and not self.symlink,'ARCHIVE_SYMLINK');return 1
    def metadata(self,fd):return self.meta
    def read(self,fd,size):
        data=self.data[self.offset:self.offset+size];self.offset+=len(data);return data
    def rewind(self,fd):self.offset=0
    def close(self,fd):self.closed=True

class SyntheticEvidenceFS:
    def __init__(self,fail=False):self.records={};self.fail=fail
    def write_exclusive(self,name,data):
        if self.fail or name in self.records:raise OSError('PRIVATE_SENTINEL')
        self.records[name]=data


def c3_self_test():
    import ast
    import copy
    tests=[]
    def check(name,value):
        require(value,'C3_SELF_TEST');tests.append(name)
    def reject(name,action,code=None):
        try:action()
        except SafetyStop as error:
            check(name,code is None or str(error)==code)
        else:raise SafetyStop('C3_SELF_TEST')
    check_immutable();check('C3 immutable checkpoint',True)
    # All OS backend calls hit the unconditional lock before any actual operation.
    reject('C3 OS spawn locked',lambda:LockedOSBackend().spawn([],{}),'C2_LIVE_TRANSPORT_LOCKED')
    reject('C3 default bounded transport locked',lambda:BoundedTransport().call('createdb'),'C2_LIVE_TRANSPORT_LOCKED')
    reject('C3 archive open locked',lambda:LockedArchiveFS().open(ARCHIVE),'C2_LIVE_TRANSPORT_LOCKED')
    reject('C3 signal backend locked',lambda:LockedSignalBackend().request('SELECT 1'),'C2_LIVE_TRANSPORT_LOCKED')
    reject('C3 evidence backend locked',lambda:LockedEvidenceFS().write_exclusive('qualification-summary.json',b''),'C2_LIVE_TRANSPORT_LOCKED')
    reject('C3 collector locked',lambda:LockedObservations(None,{},()).collect(),'C2_LIVE_TRANSPORT_LOCKED')
    for kind,kwargs,code in [('spawn',{},'PROCESS_IO_FAILURE'),('blocked',{'blocked':True},'PROCESS_TIMEOUT'),
                             ('broken',{'broken':True},'PROCESS_IO_FAILURE'),('stdout',{'output':b'x'*1025},'PROCESS_OUTPUT_OVERFLOW'),
                             ('stderr',{'error':b'x'*(MAX_DIAGNOSTIC+1)},'PROCESS_OUTPUT_OVERFLOW'),('exit',{'code':1},'PROCESS_FAILED')]:
        clock=SyntheticClock();child=SyntheticProcess(**kwargs);backend=SyntheticBackend(child,kind=='spawn')
        transport=BoundedTransport(backend,clock.now,clock.pause)
        reject('C3 transport '+kind,lambda:transport.call('identity',b'fixture',timeout=.02,maximum=1024),code)
        check('C3 no retry '+kind,len(backend.calls)==1)
        if kind!='spawn':check('C3 pipes detached '+kind,child.detached)
    clock=SyntheticClock();child=SyntheticProcess(output=b'{}');backend=SyntheticBackend(child)
    check('C3 bounded transport success',BoundedTransport(backend,clock.now,clock.pause).call('identity',b'fixture')==b'{}')
    check('C3 environment sanitized',backend.calls[0][1]==process_environment() and '--shell' not in backend.calls[0][0])
    reject('C3 arbitrary command blocked',lambda:BoundedTransport(backend).call('drop'))
    reject('C3 production cannot be restore argv',lambda:fixed_command('restore','alrifai',CLUSTER))
    check('C3 container environment cleared','-i' in psql_argv('alrifai') and '/usr/bin/env' in psql_argv('alrifai'))
    production=production_sql()
    check('C3 separate production guard',"current_database()='alrifai'" in production and 'qualification_guard' not in production and
          production.index('\\if :observation_guard')<production.index('SELECT * FROM public.'))
    check('C3 qualification guard preserved',hashlib.sha256((ROOT/'read-plan.sql').read_bytes()).hexdigest()==IMMUTABLE['read-plan.sql'])
    fixture=b'PGDMPsynthetic-only'
    def descriptor(fs=None,sha=None):
        return ArchiveDescriptor(SyntheticArchiveFS(fixture) if fs is None else fs,
            hashlib.sha256(fixture).hexdigest() if sha is None else sha,len(fixture))
    arc=descriptor();check('C3 same descriptor stream',arc.read(65536)==fixture);arc.read(1);arc.finish();arc.close()
    reject('C3 symlink archive',lambda:descriptor(SyntheticArchiveFS(fixture,True)))
    reject('C3 checksum archive',lambda:descriptor(sha='0'*64))
    for name,transform in [('replacement',lambda m:(m[0],99,*m[2:])),('truncate',lambda m:(*m[:2],1,*m[3:])),
                           ('mtime',lambda m:(*m[:3],99,*m[4:])),('permission',lambda m:(*m[:-1],stat.S_IFREG|0o644))]:
        fs=SyntheticArchiveFS(fixture);arc=descriptor(fs);fs.meta=transform(fs.meta)
        reject('C3 archive drift '+name,lambda:arc.read(1),'ARCHIVE_DRIFT');arc.close()
    fs=SyntheticArchiveFS(fixture);arc=descriptor(fs);fs.data=b'PGDMPaltered-bytes!';arc.read(65536)
    reject('C3 in-place checksum drift',arc.finish);arc.close()
    actual=dict(database='postgres',user='vps_pg_admin',cluster=CLUSTER,version='16.15',readOnly='on',
                targetExists=False,targetSessions=0,appTargets=['alrifai'])
    observed=dict(container=CONTAINER,image=IMAGE,appTarget='alrifai',healthy=True,permissionsOK=True,
        conflictingMaintenance=False,configUnchanged=True,windowOK=True,clientVersion='16.15')
    class Facts:
        def collect(self):return observed
    class Reply:
        def __init__(self,value):self.value=value
        def call(self,*args,**kwargs):return json.dumps(self.value).encode()
    check('C3 collector success',PreflightCollector(Reply(actual),Facts()).collect()['target']==TARGET)
    for key,value in [('database','alrifai'),('user','wrong'),('cluster','wrong'),('version','wrong'),('readOnly','off'),
                      ('targetExists',True),('targetSessions',1),('appTargets',[TARGET])]:
        reject('C3 live facts '+key,lambda k=key,v=value:PreflightCollector(Reply({**actual,k:v}),Facts()).collect())
    for key,value in [('container','wrong'),('image','wrong'),('appTarget',TARGET),('healthy',False),('configUnchanged',False),('windowOK',False)]:
        old=observed.copy();observed[key]=value
        reject('C3 host facts '+key,lambda:PreflightCollector(Reply(actual),Facts()).collect());observed=old
    limits=dict(minimumFreeBytes=100,minimumAvailableMemoryBytes=100,maximumRestoreSeconds=1,
                monitorIntervalSeconds=.1,maximumCpuPercent=90,maximumWalBytes=100,maximumLockSeconds=2)
    def sample(elapsed):return dict(elapsedSeconds=elapsed,freeBytes=1000,availableMemoryBytes=1000,
                                    cpuPercent=1,walBytes=0,lockSeconds=0,healthy=True)
    entered=threading.Event();release=threading.Event();samples=[]
    def collecting(elapsed):samples.append(elapsed);entered.set();return sample(elapsed)
    monitor=ConcurrentMonitor(collecting,limits);monitor.start()
    worker=threading.Thread(target=lambda:release.wait(.3),daemon=True);worker.start()
    deadline=time.monotonic()+.5
    while len(samples)<2 and time.monotonic()<deadline:time.sleep(.005)
    check('C3 monitoring while operation blocked',len(samples)>=2 and worker.is_alive())
    release.set();worker.join(.5);monitor.check();monitor.close()
    def failed(elapsed):raise OSError('PRIVATE_SENTINEL')
    monitor=ConcurrentMonitor(failed,limits);reject('C3 concurrent monitor failure',monitor.start);monitor.close()
    clock=SyntheticClock();monitor=ConcurrentMonitor(sample,limits,clock.now);monitor.start();clock.value=.2
    reject('C3 stale sample',monitor.check,'MONITOR_STALE');monitor.close()
    for key,value in [('freeBytes',0),('availableMemoryBytes',0),('cpuPercent',91),('walBytes',101),('lockSeconds',3),('healthy',False)]:
        monitor=ConcurrentMonitor(lambda elapsed,k=key,v=value:{**sample(elapsed),k:v},limits)
        reject('C3 concurrent threshold '+key,monitor.start);monitor.close()
    good=dict(status='PASS',readOnly=True,fingerprints=FINGERPRINTS)
    check('C3 bridge parsed',NodeComparator(Reply(good)).compare('target',b'fixture')['status']=='PASS')
    for result in [dict(status='PASS',readOnly=False,fingerprints=FINGERPRINTS),{**good,'fingerprints':{}},{**good,'status':'BLOCKED'}]:
        reject('C3 comparator output rejected',lambda r=result:NodeComparator(Reply(r)).compare('target',b'fixture'))
    reject('C3 bridge invalid UTF8',lambda:NodeComparator(Reply(good)).compare('target',b'\xff'))
    session=dict(database=TARGET,applicationName=APP_NAME,user='vps_pg_admin',backendType='client backend',clientAddress=None,
                 pid=123,backendStart='2026-10-08T06:00:00Z')
    captured=dict(pid=123,backendStart=session['backendStart']);window=('2026-10-08T05:59:00Z','2026-10-08T06:01:00Z')
    approval=dict(stage='C',target=TARGET,cluster=CLUSTER,archiveSHA256=ARCHIVE_SHA,signals=['cancel'])
    observation=dict(cluster=CLUSTER,sessions=[session]);calls=[]
    def observe():return observation
    def signal(sql):calls.append(sql);return True
    clock=SyntheticClock();cancel=CancellationObserver(observe,signal,clock.now,clock.pause)
    reject('C3 unauthorized termination',lambda:cancel.request('terminate',approval,captured,window,.02));check('C3 no unauthorized signal',not calls)
    observation={'cluster':CLUSTER,'sessions':[session,session]}
    reject('C3 ambiguous session',lambda:cancel.request('cancel',approval,captured,window,.02));check('C3 no ambiguous signal',not calls)
    observation={'cluster':CLUSTER,'sessions':[{**session,'backendStart':'2026-10-08T06:00:01Z'}]}
    reject('C3 PID reuse',lambda:cancel.request('cancel',approval,captured,window,.02));check('C3 no reused signal',not calls)
    observation={'cluster':CLUSTER,'sessions':[session]}
    reject('C3 cessation timeout',lambda:cancel.request('cancel',approval,captured,window,.02),'CESSATION_TIMEOUT')
    count=[0]
    def ceased():
        count[0]+=1;return dict(cluster=CLUSTER,sessions=[session] if count[0]==1 else [])
    check('C3 confirmed cessation observation',CancellationObserver(ceased,signal).request('cancel',approval,captured,window,.1)['status']=='CESSATION_OBSERVED')
    check('C3 server-side signal predicate',"backend_start='" in calls[-1] and "datname='"+TARGET+"'" in calls[-1])
    for label,args,expected in [('before',(False,False,False,True),'NOT_ATTEMPTED'),('during',(True,False,False,True),'UNKNOWN'),
                                ('after',(True,True,False,True),'UNKNOWN'),('unqualified',(True,True,False,False),'UNQUALIFIED')]:
        check('C3 commit '+label,commit_outcome(*args)==expected)
    fs=SyntheticEvidenceFS();diagnostics=DiagnosticEvidence(fs)
    record=diagnostics.write('qualification-failure.json',dict(code='PRIVATE_SENTINEL',phase='PRIVATE_SENTINEL',commitOutcome='PRIVATE_SENTINEL',payload='PRIVATE_SENTINEL'))
    check('C3 diagnostic redaction','PRIVATE_SENTINEL' not in json.dumps(record) and 'PRIVATE_SENTINEL' not in str(fs.records))
    reject('C3 diagnostic collision',lambda:diagnostics.write('qualification-failure.json',{}),'EVIDENCE_WRITE_FAILED')
    reject('C3 diagnostic filesystem failure',lambda:DiagnosticEvidence(SyntheticEvidenceFS(True)).write('qualification-failure.json',{}),'EVIDENCE_WRITE_FAILED')
    reject('C3 diagnostic traversal',lambda:diagnostics.write('../other',{}),'EVIDENCE_NAME')


    check('C3 captured unique session',capture_restore_session(dict(cluster=CLUSTER,sessions=[session]),window)==captured)
    reject('C3 capture wrong user',lambda:capture_restore_session(dict(cluster=CLUSTER,sessions=[{**session,'user':'wrong'}]),window))
    count=[0]
    def reconnected():
        count[0]+=1;return dict(cluster=CLUSTER,sessions=[session] if count[0]==1 else [{**session,'pid':999}])
    reject('C3 new restore backend not cessation',lambda:CancellationObserver(reconnected,signal).request('cancel',approval,captured,window,.1),'CANCEL_SESSION_CHANGED')
    blocked_collector=threading.Event()
    def block_sample(elapsed):blocked_collector.wait(.5);return sample(elapsed)
    monitor=ConcurrentMonitor(block_sample,limits)
    reject('C3 monitor start liveness timeout',monitor.start,'MONITOR_START_TIMEOUT')
    blocked_collector.set();monitor.close()
    require('PRIVATE_SENTINEL' not in json.dumps(diagnostic_record([],{},[])), 'C3_SELF_TEST')
    check('C3 malformed diagnostics sanitized',True)

    # Full bounded-component lifecycle, with no actual archive/database records.
    class FixtureArchive(ArchiveDescriptor):
        def __init__(self):self.expected_sha=ARCHIVE_SHA;self.expected_size=1608294;self.sent=False;self.closed=False
        def check(self):pass
        def read(self,size):
            if self.sent:return b''
            self.sent=True;return b'synthetic-archive-stream'
        def finish(self):pass
        def close(self):self.closed=True
    class FixtureCollector:
        def collect(self,require_absent=True):
            return dict(container=CONTAINER,image=IMAGE,cluster=CLUSTER,target=TARGET,targetExists=not require_absent,
                targetSessions=0,archiveSHA256=ARCHIVE_SHA,version='16.15',clientVersion='16.15',adminDatabase='postgres',
                adminUser='vps_pg_admin',appTarget='alrifai',healthy=True,conflictingMaintenance=False,permissionsOK=True,
                windowOK=True,configUnchanged=True,freeBytes=1000,availableMemoryBytes=1000,
                appStartedAt='fixture-app-start',pgStartedAt='fixture-pg-start')
    class FixtureMonitor:
        def __init__(self,fail=False):self.stop=threading.Event();self.closed=False;self.fail=fail
        def start(self):
            if self.fail:raise SafetyStop('MONITOR_FAILED')
        def check(self):
            if self.fail:raise SafetyStop('MONITOR_FAILED')
        def close(self):self.closed=True
    class LifecycleBackend:
        def __init__(self,failure=None):self.failure=failure;self.calls=[];self.comparisons=0
        def spawn(self,argv,environment):
            operation='compare' if argv[0]==NODE else ('createdb' if '/usr/local/bin/createdb' in argv else
                ('restore' if '/usr/local/bin/pg_restore' in argv else 'read'))
            self.calls.append(operation)
            if self.failure=='spawn-'+operation:raise OSError('PRIVATE_SENTINEL')
            if operation=='compare':
                self.comparisons+=1
                mode='PASS' if self.comparisons==2 else 'OBSERVED'
                fingerprints=FINGERPRINTS.copy()
                if self.failure=='production-drift' and self.comparisons==3:fingerprints['state']='0'*64
                output=json.dumps(dict(status=mode,readOnly=True,fingerprints=fingerprints)).encode()
            else:output=b'fixture-frames'
            return SyntheticProcess(output=output,code=1 if self.failure==operation else 0)
    execution_approval=dict(stage='C',target=TARGET,cluster=CLUSTER,archiveSHA256=ARCHIVE_SHA,actions=['create','restore','verify'])
    for failure in [None,'createdb','restore','spawn-restore','production-drift','monitor']:
        clock=SyntheticClock();backend=LifecycleBackend(failure);transport=BoundedTransport(backend,clock.now,clock.pause)
        archive=FixtureArchive();fs=SyntheticEvidenceFS();monitor=FixtureMonitor(failure=='monitor')
        adapter=FixedTargetAdapter(transport)
        result=adapter.run_components(FixtureCollector(),archive,execution_approval,limits,DiagnosticEvidence(fs),monitor)
        check('C3 lifecycle '+str(failure),result['status']==('COMPONENT_PASS' if failure is None else 'STOP'))
        check('C3 lifecycle retains no retry '+str(failure),not result['retry'] and not result['fallback'] and not result['cleanup'] and not result['restart'])
        check('C3 lifecycle closes '+str(failure),archive.closed and monitor.closed)
        check('C3 one restore attempt '+str(failure),backend.calls.count('restore')<=1)
        if failure in ('restore','spawn-restore'):
            check('C3 lifecycle uncertain commit '+str(failure),result['commitOutcome']=='UNKNOWN' and not result['cessationConfirmed'])
        previous=len(backend.calls)
        second=adapter.run_components(FixtureCollector(),FixtureArchive(),execution_approval,limits,DiagnosticEvidence(SyntheticEvidenceFS()))
        check('C3 lifecycle retry blocked '+str(failure),second['status']=='STOP' and len(backend.calls)==previous)

    tree=ast.parse((ROOT/'restore-supervisor.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch_live')
    check('C3 unconditional lock AST',len(function.body)==1 and isinstance(function.body[0],ast.Raise))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    check('C3 CLI no component launch',not any(isinstance(n,ast.Attribute) and n.attr in {'run_components','spawn','request','write_exclusive'} for n in ast.walk(function)))
    check('C3 no shell true',not any(isinstance(n,ast.keyword) and n.arg=='shell' and isinstance(n.value,ast.Constant) and n.value.value is True for n in ast.walk(tree)))
    return dict(status='PASS',tests=len(tests),cases=tests,realCommands=0,databaseConnections=0,signals=0,fixtures='SYNTHETIC_ONLY')



# C4: dedicated read-only gate. Operational approval is external, never inferred
# from JSON/CLI/environment. This gate also remains unconditional in this stage.
def launch_readonly():
    raise SafetyStop('C4_READONLY_INTEGRATION_NOT_AUTHORIZED')

SQL_SHA = {
 'identity':'d6258868ed0eb899e205fcb5c001de2251b3b8058a695720798e93ab4d848164',
 'resources':'e4d1a5f192b46975203f80affe6527087a80d20d7281153684dc14fc01348eaf',
 'production':'282196103d2d9117e36bfa2221855f2597f7fda87659ffc9f54ecd1ee30e04bb',
}
READONLY_OPERATIONS = ('identity','resources','production','compare','inspect-pg','inspect-app',
                       'version','archive-version','archive-list','node-version')


def readonly_commands():
    return {
      'identity':psql_argv('postgres'), 'resources':psql_argv('postgres'), 'production':psql_argv('alrifai'),
      'compare':[NODE,'--input-type=module','-e',NODE_BRIDGE],
      'inspect-pg':['/usr/bin/docker','inspect','--format','{{json .}}',CONTAINER],
      'inspect-app':['/usr/bin/docker','inspect','--format','{{json .}}','al-rifai-app-1'],
      'version':['/usr/bin/docker','exec',CONTAINER,'/usr/local/bin/psql','--version'],
      'archive-version':['/usr/bin/docker','exec',CONTAINER,'/usr/local/bin/pg_restore','--version'],
      'archive-list':['/usr/bin/docker','exec','-i',CONTAINER,'/usr/bin/env','-i',
                      'PATH=/usr/local/bin:/usr/bin:/bin','LANG=C','TZ=UTC','/usr/local/bin/pg_restore','--list'],
      'node-version':[NODE,'--version'],
    }


def argv_digest(argv):
    return hashlib.sha256(json.dumps(argv,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

# Pinned command hashes are populated below as source literals during implementation.
READONLY_ARGV_SHA = {'identity': '2c3f0d0b13d7c0f2ef0056f575e5a1591ce9a2ca4b3302f94e8f516be4689856', 'resources': '2c3f0d0b13d7c0f2ef0056f575e5a1591ce9a2ca4b3302f94e8f516be4689856', 'production': 'd46e5b6cf8167b3294a40752388c048a13a860b75dd422c1c4f2866068808fd7', 'compare': '6f99665c43b029d99e87bc0f7d0dd7d84533b957fac458d93e42c9971f0ff478', 'inspect-pg': 'd93abd43e1d7dea1df0d402aa1762107fb97448643294ed702f614702106e327', 'inspect-app': '22dd19193a79de5b1970cea5600e19ed2cf824c4ddcb9cb5436cd357da4adf66', 'version': '43c66ce38edbb36555d7a2dabe87c4cb53e100b00a24fbbeb820877c118f0876', 'archive-version': '200ef421f9d34c9e42f2c7354c7ad4f5ce8715e105bf37691e80b3726a7d94b5', 'archive-list': '5a514020b03ac16a6dff1e3836eb79463d0099e2312189a7acea3ef280b8288b', 'node-version': '27f7e03bbe9532c30d6c4ae7de55d79e5ef5740dbfa0a32b65b51b85ee8f488a'}


def validate_readonly_command(operation, argv, environment):
    require(operation in READONLY_OPERATIONS, 'READONLY_OPERATION')
    require(type(argv) is list and argv == readonly_commands()[operation], 'READONLY_ARGV')
    require(argv_digest(argv) == READONLY_ARGV_SHA[operation], 'READONLY_ARGV_HASH')
    require(environment == process_environment(), 'READONLY_ENVIRONMENT')


class LockedReadOnlyOSBackend:
    def spawn(self, argv, environment):
        operations=[k for k,v in readonly_commands().items() if argv==v]
        require(bool(operations), 'READONLY_ARGV')
        validate_readonly_command(operations[0],argv,environment)
        launch_readonly()
        import subprocess
        return OSProcess(subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,env=environment,shell=False,close_fds=True))


class LockedReadOnlyArchiveFS(LockedArchiveFS):
    def open(self,path):
        launch_readonly()
        return secure_archive_open(path)


class LockedReadOnlyObservations(LockedObservations):
    # This dormant collector reuses fixed observations without changing the
    # original restore collector's gate; the narrow transport prevents mutation.
    def collect(self):
        launch_readonly()
        return readonly_host_collect(self)

    def resources(self):
        launch_readonly()
        return readonly_host_resources(self)

    def warmup(self):
        launch_readonly()
        cpu=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        self.previous_cpu=(sum(cpu),cpu[3]+cpu[4])


def readonly_host_collect(observer):
    # Host logic is shared from the reviewed collector by an explicit pure
    # function extracted below. No call to a restore backend occurs here.
    return host_observation_collect(observer)


def readonly_host_resources(observer):
    return host_observation_resources(observer)


class ReadOnlyTransport:
    def __init__(self,backend=None,clock=time.monotonic,pause=time.sleep):
        self.backend=LockedReadOnlyOSBackend() if backend is None else backend
        self.clock,self.pause=clock,pause
        self.database_slots=threading.BoundedSemaphore(2)
        self.used_production=0
        self.deadline=None
        self.process_limit=20
        self.state_lock=threading.Lock()

    def bind_window(self,seconds,process_seconds):
        require(self.deadline is None and finite_number(seconds) and 0<seconds<=120
                and finite_number(process_seconds) and 0<process_seconds<=20,'READONLY_CONFIG')
        self.deadline=self.clock()+seconds
        self.process_limit=process_seconds

    def call(self,operation,data=b'',timeout=20,maximum=MAX_FRAMES,stop=None,watchdog=None):
        require(operation in READONLY_OPERATIONS,'READONLY_OPERATION')
        require(finite_number(timeout) and 0<timeout<=20,'PROCESS_LIMIT')
        timeout=min(timeout,self.process_limit)
        if self.deadline is not None:
            timeout=min(timeout,self.deadline-self.clock())
            require(timeout>0,'READONLY_WINDOW_EXPIRED')
        cap=(32*1024*1024 if operation=='production' else 1024 if operation in
             ('version','archive-version','node-version') else MAX_DIAGNOSTIC)
        require(type(maximum) is int and 0<maximum<=MAX_FRAMES,'PROCESS_LIMIT')
        maximum=min(maximum,cap)
        argv=readonly_commands()[operation]
        validate_readonly_command(operation,argv,process_environment())
        if operation in SQL_SHA:
            require(type(data) is bytes and hashlib.sha256(data).hexdigest()==SQL_SHA[operation],'READONLY_SQL_HASH')
        elif operation=='compare':
            require(type(data) is bytes and len(data)<=MAX_FRAMES,'FRAME_LIMIT')
            try:packet=json.loads(data)
            except Exception:raise SafetyStop('COMPARATOR_FAILURE') from None
            require(type(packet) is dict and set(packet)=={'mode','frames'} and packet['mode']=='production'
                    and type(packet['frames']) is str,'READONLY_COMPARATOR_MODE')
        elif operation=='archive-list':
            require(isinstance(data,ArchiveDescriptor) and data.expected_sha==ARCHIVE_SHA
                    and data.expected_size==1608294,'ARCHIVE')
            data.check()
        else:
            require(data==b'','READONLY_INPUT')
        db=operation in SQL_SHA
        require(not db or self.database_slots.acquire(blocking=False),'CONNECTION_LIMIT')
        try:
            if operation=='production':
                with self.state_lock:
                    require(self.used_production<2,'READONLY_REPEAT_DISABLED')
                    self.used_production+=1
            # Reuse the bounded pump only. The generic command registry is never called.
            return BoundedTransport._pump(self,argv,data,timeout,maximum,stop,watchdog,operation=='archive-list')
        finally:
            if db:self.database_slots.release()


def readonly_config(config):
    require(type(config) is dict and set(config)=={'limits','startupSeconds','acquisitionSeconds','freshnessSeconds',
                                                'processSeconds','durationSeconds'},'READONLY_CONFIG')
    validate_limits(config['limits'])
    require(all(finite_number(v) and v>0 for k,v in config.items() if k!='limits'),'READONLY_CONFIG')
    require(config['processSeconds']<=20 and config['durationSeconds']<=120 and
            config['startupSeconds']<=20 and config['acquisitionSeconds']<=config['freshnessSeconds']
            and config['freshnessSeconds']<=config['limits']['monitorIntervalSeconds']
            and config['limits']['maximumRestoreSeconds']==config['durationSeconds'], 'READONLY_CONFIG')
    # Explicit config binds thresholds; it is not owner authorization.
    return config


class ReadOnlyIntegration:
    def __init__(self,transport,collector,archive,config,clock=time.monotonic,pause=time.sleep):
        require(type(transport) is ReadOnlyTransport,'READONLY_TRANSPORT_REQUIRED')
        self.transport,self.collector,self.archive=transport,collector,archive
        self.config=readonly_config(config)
        self.clock,self.pause=clock,pause
        self.used=False

    def run(self):
        monitor=None
        try:
            require(not self.used,'READONLY_REPEAT_DISABLED');self.used=True
            check_immutable()
            self.transport.bind_window(self.config['durationSeconds'],self.config['processSeconds'])
            before_state=self.collector.collect()
            require(before_state['container']==CONTAINER and before_state['cluster']==CLUSTER
                    and before_state['adminUser']=='vps_pg_admin' and before_state['targetExists'] is False
                    and before_state['appTarget']=='alrifai','PREFLIGHT_IDENTITY')
            for operation in ('version','archive-version'):
                version=self.transport.call(operation,timeout=self.config['processSeconds']).decode('ascii').strip()
                require(version.endswith('16.15'),'VERSION')
            node=self.transport.call('node-version',timeout=self.config['processSeconds']).decode('ascii').strip()
            require(node.startswith('v') and node[1:].split('.')[0].isdigit() and int(node[1:].split('.')[0])>=22,'NODE_VERSION')
            listing=self.transport.call('archive-list',self.archive,timeout=self.config['processSeconds'])
            headers={}
            for line in listing.decode('utf8').splitlines():
                if line.startswith(';') and ':' in line:
                    key,value=line[1:].split(':',1);headers[key.strip()]=value.strip()
            require(headers.get('Format')=='CUSTOM' and headers.get('Dump Version')=='1.15-0'
                    and headers.get('TOC Entries')=='34','ARCHIVE_TOC')
            self.archive.check()
            before=NodeComparator(self.transport).compare('production',self.transport.call('production',production_sql().encode(),timeout=self.config['processSeconds']))
            require(before['fingerprints']==FINGERPRINTS,'PRODUCTION_BASELINE')
            monitor=ConcurrentMonitor(self.collector.resource_sample,self.config['limits'],self.clock,self.config)
            monitor.start()
            started=self.clock()
            # Bounded observation window; no restore lifecycle or signal callback.
            until=min(self.config['durationSeconds']-self.config['startupSeconds']-2*self.config['processSeconds'],
                      self.config['limits']['monitorIntervalSeconds'])
            require(until>0,'READONLY_CONFIG')
            while self.clock()-started<until:
                monitor.check();self.pause(.005)
            after=NodeComparator(self.transport).compare('production',self.transport.call('production',production_sql().encode(),
                timeout=self.config['processSeconds'],watchdog=monitor.check))
            require(after['fingerprints']==before['fingerprints'],'PRODUCTION_CHANGED')
            after_state=self.collector.collect()
            require(all(after_state.get(key)==before_state[key] for key in
                    ('container','cluster','adminUser','targetExists','appTarget','appStartedAt','pgStartedAt')),
                    'PRODUCTION_CHANGED')
            monitor.check();monitor.close();monitor=None
            return {'status':'READONLY_COMPONENT_PASS','fingerprints':after['fingerprints'],
                    'archiveTOCSHA256':hashlib.sha256(listing).hexdigest(),'qualified':False,
                    'retry':False,'fallback':False,'cleanup':False,'signals':0}
        except Exception:
            return {'status':'STOP','code':'READONLY_INTEGRATION_FAILED','qualified':False,
                    'retry':False,'fallback':False,'cleanup':False,'signals':0,'cessationConfirmed':False}
        finally:
            if monitor is not None:
                try:monitor.close()
                except Exception:pass
            self.archive.close()


def readonly_entrypoint(config=None,reference=None,window=None):
    launch_readonly()
    # Dormant wiring only; no JSON/flag authenticates permission to reach here.
    config=readonly_config(config)
    transport=ReadOnlyTransport()
    observations=LockedReadOnlyObservations(transport,reference,window)
    collector=PreflightCollector(transport,observations)
    archive=ArchiveDescriptor(LockedReadOnlyArchiveFS())
    return ReadOnlyIntegration(transport,collector,archive,config).run()



def c4_self_test():
    import ast
    tests=[]
    def check(name,value):require(value,'C4_SELF_TEST');tests.append(name)
    def reject(name,action,code=None):
        try:action()
        except SafetyStop as error:check(name,code is None or str(error)==code)
        else:raise SafetyStop('C4_SELF_TEST')
    for operation,sql in [('identity',observation_sql()),('resources',resource_sql()),('production',production_sql())]:
        check('C4 SQL pin '+operation,hashlib.sha256(sql.encode()).hexdigest()==SQL_SHA[operation])
        child=SyntheticProcess(output=b'{}');backend=SyntheticBackend(child);clock=SyntheticClock()
        transport=ReadOnlyTransport(backend,clock.now,clock.pause)
        reject('C4 changed SQL '+operation,lambda op=operation,b=sql.encode():transport.call(op,b+b' '),'READONLY_SQL_HASH')
        check('C4 tampered SQL not spawned '+operation,not backend.calls)
    for operation in READONLY_OPERATIONS:
        argv=readonly_commands()[operation]
        validate_readonly_command(operation,argv,process_environment())
        check('C4 argv pin '+operation,argv_digest(argv)==READONLY_ARGV_SHA[operation])
        reject('C4 argv alteration '+operation,lambda op=operation,a=argv:validate_readonly_command(op,a+['--clean'],process_environment()))
    for operation in ['createdb','restore','target','cancel','terminate','cleanup','restart','generic']:
        backend=SyntheticBackend();transport=ReadOnlyTransport(backend)
        reject('C4 denied operation '+operation,lambda op=operation:transport.call(op),'READONLY_OPERATION')
        check('C4 denied no spawn '+operation,not backend.calls)
    for key,value in [('PGDATABASE','alrifai'),('LD_PRELOAD','PRIVATE_SENTINEL'),('DOCKER_HOST','PRIVATE_SENTINEL')]:
        reject('C4 environment injection '+key,lambda k=key,v=value:validate_readonly_command('identity',psql_argv('postgres'),{**process_environment(),k:v}))
    for index,value in [(3,'wrong'),(psql_argv('postgres').index('vps_pg_admin'),'wrong'),
                        (psql_argv('postgres').index('postgres'),'alrifai'),(psql_argv('postgres').index('/var/run/postgresql'),'/tmp')]:
        argv=psql_argv('postgres');argv[index]=value
        reject('C4 identity argv alteration',lambda a=argv:validate_readonly_command('identity',a,process_environment()))
    reject('C4 readonly OS locked',lambda:ReadOnlyTransport().call('identity',observation_sql().encode()),'C4_READONLY_INTEGRATION_NOT_AUTHORIZED')
    reject('C4 readonly entrypoint locked',readonly_entrypoint,'C4_READONLY_INTEGRATION_NOT_AUTHORIZED')
    reject('C4 restore lock unchanged',launch_live,'C2_LIVE_TRANSPORT_LOCKED')
    reject('C4 readonly archive locked',lambda:LockedReadOnlyArchiveFS().open(ARCHIVE),'C4_READONLY_INTEGRATION_NOT_AUTHORIZED')
    reject('C4 compare target mode denied',lambda:ReadOnlyTransport(SyntheticBackend()).call('compare',b'{"mode":"target","frames":"fixture"}'),'READONLY_COMPARATOR_MODE')
    reject('C4 comparator malformed',lambda:ReadOnlyTransport(SyntheticBackend()).call('compare',b'PRIVATE_SENTINEL'),'COMPARATOR_FAILURE')
    class FixtureArchive(ArchiveDescriptor):
        def __init__(self):self.expected_sha=ARCHIVE_SHA;self.expected_size=1608294;self.offset=0;self.closed=False;self.drift=False
        def check(self):require(not self.drift,'ARCHIVE_DRIFT')
        def read(self,size):self.check();self.offset+=size;return b'fixture' if self.offset<=65536 else b''
        def close(self):self.closed=True
    class EarlyProcess(SyntheticProcess):
        def write(self,data):raise BrokenPipeError('PRIVATE_SENTINEL')
        def poll(self):return 0
    toc=b'; Format: CUSTOM\n; Dump Version: 1.15-0\n; TOC Entries: 34\n'
    child=EarlyProcess(output=toc);clock=SyntheticClock();transport=ReadOnlyTransport(SyntheticBackend(child),clock.now,clock.pause)
    check('C4 early listing closure accepted',transport.call('archive-list',FixtureArchive())==toc and child.detached)
    archive=FixtureArchive();archive.drift=True;backend=SyntheticBackend()
    reject('C4 listing drift denied',lambda:ReadOnlyTransport(backend).call('archive-list',archive),'ARCHIVE_DRIFT')
    check('C4 drift no spawn',not backend.calls)
    archive=FixtureArchive();archive.expected_sha='0'*64
    reject('C4 listing checksum identity',lambda:ReadOnlyTransport(SyntheticBackend()).call('archive-list',archive),'ARCHIVE')
    for kind,kwargs,expected in [('blocked',{'blocked':True},'PROCESS_TIMEOUT'),('overflow',{'output':b'x'*(MAX_DIAGNOSTIC+1)},'PROCESS_OUTPUT_OVERFLOW')]:
        clock=SyntheticClock();backend=SyntheticBackend(SyntheticProcess(**kwargs))
        reject('C4 bounded '+kind,lambda:ReadOnlyTransport(backend,clock.now,clock.pause).call('identity',observation_sql().encode(),timeout=.02),expected)
        check('C4 bounded no retry '+kind,len(backend.calls)==1)
    transport=ReadOnlyTransport(SyntheticBackend())
    transport.database_slots.acquire();transport.database_slots.acquire()
    reject('C4 third DB connection denied',lambda:transport.call('identity',observation_sql().encode()),'CONNECTION_LIMIT')
    transport.database_slots.release();transport.database_slots.release()
    check('C4 connection slots released',transport.database_slots.acquire(False) and transport.database_slots.acquire(False))
    transport.database_slots.release();transport.database_slots.release()
    clock=SyntheticClock();transport=ReadOnlyTransport(SyntheticBackend(),clock.now,clock.pause);transport.bind_window(.1,.05);clock.value=.2
    reject('C4 expired observation window',lambda:transport.call('identity',observation_sql().encode()),'READONLY_WINDOW_EXPIRED')
    config=dict(limits=dict(minimumFreeBytes=100,minimumAvailableMemoryBytes=100,maximumRestoreSeconds=1,
                monitorIntervalSeconds=.04,maximumCpuPercent=90,maximumWalBytes=100,maximumLockSeconds=2),
                startupSeconds=.1,acquisitionSeconds=.02,freshnessSeconds=.04,processSeconds=.1,durationSeconds=1)
    readonly_config(config)
    reject('C4 missing explicit thresholds',lambda:readonly_config({}))
    reject('C4 contradictory timing',lambda:readonly_config({**config,'acquisitionSeconds':.2}))
    def sample(elapsed):return dict(elapsedSeconds=elapsed,freeBytes=1000,availableMemoryBytes=1000,
                                    cpuPercent=1,walBytes=0,lockSeconds=0,healthy=True)
    clock=SyntheticClock()
    def slow_sample(elapsed):clock.value+=.03;return sample(elapsed)
    monitor=ConcurrentMonitor(slow_sample,config['limits'],clock.now,config)
    reject('C4 acquisition age stops startup',monitor.start);monitor.close()
    clock=SyntheticClock();monitor=ConcurrentMonitor(sample,config['limits'],clock.now,config);monitor.start();clock.value=.05
    reject('C4 sample start freshness',monitor.check,'MONITOR_STALE');monitor.close()
    for key,value in [('freeBytes',0),('availableMemoryBytes',0),('cpuPercent',91),('walBytes',101),('lockSeconds',3),('healthy',False)]:
        monitor=ConcurrentMonitor(lambda elapsed,k=key,v=value:{**sample(elapsed),k:v},config['limits'],timing=config)
        reject('C4 threshold '+key,monitor.start);monitor.close()
    class FixtureCollector:
        def collect(self):return dict(container=CONTAINER,cluster=CLUSTER,adminUser='vps_pg_admin',targetExists=False,
                                      appTarget='alrifai',appStartedAt='fixture-app',pgStartedAt='fixture-pg')
        def resource_sample(self,elapsed):return sample(elapsed)
    class IntegrationBackend:
        def __init__(self,failure=None):self.calls=[];self.failure=failure;self.comparisons=0
        def spawn(self,argv,environment):
            op=next(k for k,v in readonly_commands().items() if argv==v);self.calls.append(op)
            if op in ('version','archive-version'):output=b'psql (PostgreSQL) 16.15\n'
            elif op=='node-version':output=b'v24.0.0\n'
            elif op=='archive-list':return EarlyProcess(output=toc)
            elif op=='compare':
                self.comparisons+=1;fingerprints=FINGERPRINTS.copy()
                if self.failure=='fingerprints' and self.comparisons==2:fingerprints['state']='0'*64
                output=json.dumps(dict(status='OBSERVED',readOnly=True,fingerprints=fingerprints)).encode()
                if self.failure=='comparator':output=b'PRIVATE_SENTINEL'
            else:output=b'fixture frames'
            return SyntheticProcess(output=output)
    for failure in [None,'fingerprints','comparator']:
        backend=IntegrationBackend(failure);transport=ReadOnlyTransport(backend)
        integration=ReadOnlyIntegration(transport,FixtureCollector(),FixtureArchive(),config)
        result=integration.run()
        check('C4 integration '+str(failure),result['status']==('READONLY_COMPONENT_PASS' if failure is None else 'STOP'))
        check('C4 memory redaction '+str(failure),'PRIVATE_SENTINEL' not in json.dumps(result))
        check('C4 no mutation calls '+str(failure),all(op in READONLY_OPERATIONS for op in backend.calls))
        count=len(backend.calls);check('C4 integration no retry '+str(failure),integration.run()['status']=='STOP' and len(backend.calls)==count)
    tree=ast.parse((ROOT/'restore-supervisor.py').read_text())
    for name in ('launch_live','launch_readonly'):
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        check('C4 unconditional AST '+name,len(fn.body)==1 and isinstance(fn.body[0],ast.Raise))
    for name in ('ReadOnlyTransport','ReadOnlyIntegration','LockedReadOnlyOSBackend'):
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
        check('C4 no generic mutation references '+name,not any(isinstance(n,ast.Attribute) and n.attr in
             {'run_components','run_mock','request','write_exclusive','createdb','restore'} for n in ast.walk(cls)))
    return dict(status='PASS',tests=len(tests),cases=tests,realCommands=0,databaseConnections=0,signals=0,
                fixtures='SYNTHETIC_ONLY')


def main():
    parser = argparse.ArgumentParser(description="Plan-only recovery tooling; live modes blocked")
    parser.add_argument("--mode", default="plan")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.mode == "readonly":
        print(json.dumps(readonly_entrypoint()));return
    require(args.mode == "plan", "LIVE_EXECUTION_NOT_AUTHORIZED")
    load_attestation()
    print(json.dumps({"stageC1": self_test(), "stageC2": c2_self_test(), "stageC3": c3_self_test(), "stageC4": c4_self_test()} if args.self_test else proposed_plan()))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, SafetyStop) else "INPUT_OR_INTERNAL_FAILURE"
        print(json.dumps({"status": "BLOCKED", "code": code, "liveExecutionEnabled": False}))
        raise SystemExit(1)
