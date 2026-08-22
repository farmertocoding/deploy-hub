"""Bounded log pulls with an honest sampled degrade (MON-C4-LOG-BACKPRESSURE, §C4).

The collector must bound what it ships and drop honestly: under the per-pull
byte cap the raw lines travel; over it the on-host one-liner aggregates counts
by status and top IPs and ships `{"sampled": true, "summary": {...}}` — a
dropped window is a recorded fact, not silence. Offsets advance by inode +
offset exactly once; rotation (new inode) resets to byte 0 without losing the
new file's head; Caddy's native roller is a versioned catalog entry so target
disk is bounded no matter what the Hub does.
"""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import monitor.collect_once as producer
from core.models import NetworkZone, Project, Site, Target

PRODUCER = Path(producer.__file__).resolve()
# Planted in a field the summary never aggregates: raw line content must not
# ride a sampled pull in any key.
MARKER = "PLANTED-RAW-LINE-do-not-ship"
TS = datetime(2026, 8, 22, 10, 0, 5, tzinfo=UTC).timestamp()


def _line(status=200, ip="203.0.113.7", host="example.com", size=512, ts=TS):
    return json.dumps({
        "ts": ts,
        "status": status,
        "size": size,
        "request": {"host": host, "remote_ip": ip, "uri": f"/{MARKER}"},
    })


def _run(log, offset=0, inode=None, target_id=42):
    argv = [sys.executable, str(PRODUCER), str(target_id), str(offset), str(log)]
    if inode is not None:
        argv.append(str(inode))
    proc = subprocess.run(argv, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout), proc.stdout


def _big_log(tmp_path, *, lines=None):
    """A log comfortably over the byte cap: 700×200 + 150×404 + 50×500."""
    log = tmp_path / "access.log"
    body = lines or (
        [_line(200, ip="203.0.113.7") for _ in range(700)]
        + [_line(404, ip="198.51.100.9") for _ in range(150)]
        + [_line(500, ip="198.51.100.9") for _ in range(50)]
    )
    log.write_text("\n".join(body) + "\n", encoding="utf-8")
    assert log.stat().st_size > producer.CHUNK
    return log


def _world(slug, domain="example.com"):
    from dns_fixtures import default_dns_zone

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project, name=slug, domain=domain, primary_target=target,
        dns_zone=default_dns_zone(),
    )
    return target, site


def _payload(target, chunk, ts="2026-08-22T10:00:30Z"):
    return {
        "schema_version": 1,
        "target_id": target.pk,
        "ts": ts,
        "metrics": {"load1": 0.5, "mem_pct": 40.0, "disk_pct": 20.0},
        "containers": [],
        "log_chunk": chunk,
        "clock": ts,
        "healthz": {"live": True, "ready": True, "checks": {}},
    }


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
def test_pull_never_exceeds_the_byte_cap(tmp_path):
    """Raw bytes shipped per pull never exceed the cap, chatty log or not.

    What would make this fail: shipping the whole pending region as raw lines,
    or a degrade path that still embeds raw line content in the payload.
    """
    log = _big_log(tmp_path)
    payload, _stdout = _run(log)
    chunk = payload["log_chunk"]
    assert len(chunk.get("bytes", "").encode("utf-8")) <= producer.CHUNK

    small = tmp_path / "small.log"
    small.write_text(_line() + "\n", encoding="utf-8")
    under, _ = _run(small)
    raw = under["log_chunk"]["bytes"]
    assert len(raw.encode("utf-8")) <= producer.CHUNK
    assert MARKER in raw  # under the cap the raw lines still travel


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
def test_over_cap_pull_returns_a_sampled_summary(tmp_path):
    """Over the cap: counts by status and top IPs, flagged sampled, no raw lines.

    What would make this fail: shipping raw lines anyway, dropping the window
    silently (no summary), or forgetting to advance the offset past what the
    one-liner consumed.
    """
    log = _big_log(tmp_path)
    payload, stdout = _run(log)
    chunk = payload["log_chunk"]

    assert chunk["sampled"] is True
    assert MARKER not in stdout
    summary = chunk["summary"]
    assert summary["requests"] == 900
    assert summary["status_counts"] == {"200": 700, "404": 150, "500": 50}
    top = [(ip, n) for ip, n in summary["top_ips"]]
    assert top[0] == ("203.0.113.7", 700)
    assert ("198.51.100.9", 200) in top
    assert summary["hosts"]["example.com"]["requests"] == 900
    assert chunk["offset"] == log.stat().st_size
    assert chunk["inode"] == log.stat().st_ino


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
@pytest.mark.django_db
def test_sampled_flag_survives_into_trafficstat(tmp_path):
    """A sampled summary lands as TrafficStat rows with sampled=True, never dropped.

    What would make this fail: ingesting the summary as if it were exact
    (sampled=False), or refusing to ingest summaries at all.
    """
    from core.models import TrafficStat
    from monitor.traffic import ingest

    target, site = _world("sampled")
    log = _big_log(tmp_path)
    produced, _ = _run(log, target_id=target.pk)
    chunk = produced["log_chunk"]
    assert chunk["sampled"] is True

    result = ingest(target, _payload(target, chunk))
    assert result["ok"] is True

    row = TrafficStat.objects.get(site=site)
    assert row.sampled is True
    assert row.granularity == TrafficStat.Granularity.MINUTE
    assert row.requests == 900
    assert row.status_counts == {"200": 700, "404": 150, "500": 50}


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
@pytest.mark.django_db
def test_offset_advances_once_and_reingest_is_a_noop(tmp_path):
    """inode+offset advance exactly once per pull; re-ingesting a chunk is a no-op.

    What would make this fail: re-reading from 0 every minute, or ingest
    double-counting the same (inode, offset) window on a retry.
    """
    from core.models import TrafficStat
    from monitor.traffic import ingest

    target, site = _world("noop")
    log = tmp_path / "access.log"
    log.write_text(_line() + "\n" + _line(404) + "\n", encoding="utf-8")

    first, _ = _run(log, target_id=target.pk)
    chunk = first["log_chunk"]
    assert chunk["offset"] == log.stat().st_size

    again, _ = _run(log, offset=chunk["offset"], inode=chunk["inode"],
                    target_id=target.pk)
    assert again["log_chunk"]["offset"] == chunk["offset"]  # advanced exactly once
    assert again["log_chunk"]["bytes"] == ""

    result = ingest(target, _payload(target, chunk))
    assert result["ok"] is True and not result.get("deduped")
    row = TrafficStat.objects.get(site=site)
    assert row.requests == 2

    target.refresh_from_db()
    redo = ingest(target, _payload(target, chunk))
    assert redo["deduped"] is True
    row.refresh_from_db()
    assert row.requests == 2  # not doubled
    assert TrafficStat.objects.filter(site=site).count() == 1


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
def test_rotated_inode_resets_offset_without_losing_the_new_file(tmp_path):
    """A new inode means a new file: the pull restarts at byte 0.

    What would make this fail: trusting the stored offset across rotation so
    the new file's head (here: larger than the old offset) is silently skipped.
    """
    log = tmp_path / "access.log"
    log.write_text(_line(200, ip="192.0.2.1") + "\n", encoding="utf-8")
    before, _ = _run(log)
    old = before["log_chunk"]
    assert old["offset"] > 0

    log.unlink()  # rotation: same path, new inode, MORE bytes than the old offset
    fresh = [_line(201, ip=f"192.0.2.{i + 2}") for i in range(10)]
    body = "\n".join(fresh) + "\n"
    log.write_text(body, encoding="utf-8")
    assert log.stat().st_ino != old["inode"]
    assert log.stat().st_size > old["offset"]

    after, _ = _run(log, offset=old["offset"], inode=old["inode"])
    chunk = after["log_chunk"]
    assert chunk["inode"] == log.stat().st_ino
    assert chunk["offset"] == log.stat().st_size
    assert chunk["bytes"] == body  # byte 0, head not lost


@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
def test_catalog_rotation_entry_has_check_fix_rollback_and_version(tmp_path):
    """Caddy's native roller is a versioned catalog entry; logrotate stays backstop.

    What would make this fail: no caddy-log-roll entry, a snippet without the
    pinned roll_size 100MiB / roll_keep 5, shell-string argv, or dropping the
    logrotate backstop entry.
    """
    from catalog.apply import argv_steps
    from catalog.entries import ENTRIES

    entry = ENTRIES["caddy-log-roll"]
    assert isinstance(entry.version, int) and entry.version >= 1
    for field in (entry.check, entry.fix, entry.rollback):
        for step in argv_steps(field):
            assert step and all(isinstance(part, str) for part in step)
            assert not (len(step) == 1 and " " in step[0])

    snippet = Path(producer.__file__).parents[1] / "catalog" / "files" / "caddy-log-roll.caddy"
    body = snippet.read_text(encoding="utf-8")
    assert "roll_size 100MiB" in body
    assert "roll_keep 5" in body

    fix_tokens = [part for step in argv_steps(entry.fix) for part in step]
    assert any("caddy-log-roll.caddy" in part for part in fix_tokens)
    assert "install" in fix_tokens
    rollback_tokens = [part for step in argv_steps(entry.rollback) for part in step]
    assert "rm" in rollback_tokens

    assert "log-rotation" in ENTRIES  # the logrotate backstop stays
