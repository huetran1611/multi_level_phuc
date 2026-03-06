#!/usr/bin/env python3
import argparse
import csv
import glob
import os
import re
import statistics
import subprocess
import time
from pathlib import Path


def parse_last_float(pattern: str, text: str, default: float = 0.0) -> float:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if not matches:
        return default
    try:
        return float(matches[-1])
    except ValueError:
        return default


def parse_solver_output(stdout: str) -> dict:
    return {
        "makespan": parse_last_float(r"^Makespan:\s*([0-9eE+.-]+)", stdout, 0.0),
        "drone_violation": parse_last_float(r"^Drone violation:\s*([0-9eE+.-]+)", stdout, 0.0),
        "waiting_violation": parse_last_float(r"^Waiting violation:\s*([0-9eE+.-]+)", stdout, 0.0),
        "fitness": parse_last_float(r"^Fitness:\s*([0-9eE+.-]+)", stdout, float("inf")),
    }


def run_cmd(cmd: list[str], timeout_sec: int) -> tuple[str, str, int, float, bool]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        elapsed = time.perf_counter() - start
        return proc.stdout, proc.stderr, proc.returncode, elapsed, False
    except subprocess.TimeoutExpired as e:
        elapsed = time.perf_counter() - start
        stdout = e.stdout if isinstance(e.stdout, str) else ""
        stderr = e.stderr if isinstance(e.stderr, str) else ""
        return stdout, stderr, 124, elapsed, True


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def mean_or_inf(values: list[float]) -> float:
    if not values:
        return float("inf")
    finite = [v for v in values if v != float("inf")]
    if not finite:
        return float("inf")
    return statistics.mean(finite)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Multilevel Time Matrix vs Pure Tabu")
    parser.add_argument("--instances-glob", default="instances/50.10.*.txt")
    parser.add_argument("--levels", default="4,5,6,7,8")
    parser.add_argument("--compressions", default="5,10,15,20", help="Percent values")
    parser.add_argument("--iter-per-segment", type=int, default=50)
    parser.add_argument("--segments-per-level", type=int, default=20)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--outdir", default="results/gha_bench")
    args = parser.parse_args()

    ensure_dir(args.outdir)
    ensure_dir("results/bench")

    instances = sorted(glob.glob(args.instances_glob))
    if not instances:
        print(f"No instances matched: {args.instances_glob}")
        return 2

    levels = [int(x.strip()) for x in args.levels.split(",") if x.strip()]
    compressions = [int(x.strip()) for x in args.compressions.split(",") if x.strip()]

    multilevel_bin = Path("results/bench/multilevel_time_gha")
    tabu_bin = Path("results/bench/tabu_gha")

    if os.name == "nt":
        multilevel_bin = Path(str(multilevel_bin) + ".exe")
        tabu_bin = Path(str(tabu_bin) + ".exe")

    compile_multi = ["g++", "-O3", "-std=c++17", "src/Multilevel_Tabu_time_matrix.cpp", "-o", str(multilevel_bin)]
    compile_tabu = ["g++", "-O3", "-std=c++17", "src/Tabu.cpp", "-o", str(tabu_bin)]

    for compile_cmd in (compile_multi, compile_tabu):
        c = subprocess.run(compile_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if c.returncode != 0:
            print("Compile failed:")
            print(" ".join(compile_cmd))
            print(c.stderr)
            return 3

    rows = []
    for level in levels:
        tabu_total_segments = args.segments_per_level * level * 2
        for compression in compressions:
            merge_ratio_arg = str(compression)
            for instance_path in instances:
                instance = os.path.basename(instance_path)
                for run_id in range(1, args.runs + 1):
                    multi_cmd = [
                        str(multilevel_bin),
                        instance_path,
                        str(level),
                        str(args.iter_per_segment),
                        str(args.segments_per_level),
                        merge_ratio_arg,
                    ]
                    out, err, code, elapsed, timed_out = run_cmd(multi_cmd, args.timeout_sec)
                    parsed = parse_solver_output(out)
                    status = "ok"
                    if timed_out:
                        status = "timeout"
                    elif code != 0:
                        status = "error"

                    rows.append(
                        {
                            "instance": instance,
                            "variant": "multilevel_time",
                            "level": level,
                            "compression_pct": compression,
                            "iter_per_segment": args.iter_per_segment,
                            "segments_per_level": args.segments_per_level,
                            "total_segments": args.segments_per_level * level,
                            "run": run_id,
                            "runtime_sec": round(elapsed, 6),
                            "makespan": parsed["makespan"],
                            "drone_violation": parsed["drone_violation"],
                            "waiting_violation": parsed["waiting_violation"],
                            "fitness": parsed["fitness"],
                            "status": status,
                            "exit_code": code,
                            "stderr_tail": err[-500:].replace("\n", " "),
                        }
                    )

                    tabu_cmd = [
                        str(tabu_bin),
                        instance_path,
                        str(args.iter_per_segment),
                        str(tabu_total_segments),
                    ]
                    out, err, code, elapsed, timed_out = run_cmd(tabu_cmd, args.timeout_sec)
                    parsed = parse_solver_output(out)
                    status = "ok"
                    if timed_out:
                        status = "timeout"
                    elif code != 0:
                        status = "error"

                    rows.append(
                        {
                            "instance": instance,
                            "variant": "pure_tabu",
                            "level": level,
                            "compression_pct": compression,
                            "iter_per_segment": args.iter_per_segment,
                            "segments_per_level": args.segments_per_level,
                            "total_segments": tabu_total_segments,
                            "run": run_id,
                            "runtime_sec": round(elapsed, 6),
                            "makespan": parsed["makespan"],
                            "drone_violation": parsed["drone_violation"],
                            "waiting_violation": parsed["waiting_violation"],
                            "fitness": parsed["fitness"],
                            "status": status,
                            "exit_code": code,
                            "stderr_tail": err[-500:].replace("\n", " "),
                        }
                    )

                    print(
                        f"DONE instance={instance} level={level} comp={compression}% run={run_id} "
                        f"multi_fit={rows[-2]['fitness']:.6f} tabu_fit={rows[-1]['fitness']:.6f}"
                    )

    level_tag = "-".join(str(x) for x in levels)
    comp_tag = "-".join(str(x) for x in compressions)
    raw_csv = Path(args.outdir) / f"raw_L{level_tag}_C{comp_tag}.csv"

    with raw_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance",
                "variant",
                "level",
                "compression_pct",
                "iter_per_segment",
                "segments_per_level",
                "total_segments",
                "run",
                "runtime_sec",
                "makespan",
                "drone_violation",
                "waiting_violation",
                "fitness",
                "status",
                "exit_code",
                "stderr_tail",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    grouped = {}
    for r in rows:
        key = (r["instance"], r["level"], r["compression_pct"], r["variant"])
        grouped.setdefault(key, []).append(r)

    summary_rows = []
    for (instance, level, compression, variant), rr in sorted(grouped.items()):
        fitness_vals = [x["fitness"] for x in rr]
        runtime_vals = [x["runtime_sec"] for x in rr]
        ok_count = sum(1 for x in rr if x["status"] == "ok")
        timeout_count = sum(1 for x in rr if x["status"] == "timeout")
        error_count = sum(1 for x in rr if x["status"] == "error")
        summary_rows.append(
            {
                "instance": instance,
                "level": level,
                "compression_pct": compression,
                "variant": variant,
                "runs": len(rr),
                "ok_runs": ok_count,
                "timeout_runs": timeout_count,
                "error_runs": error_count,
                "fitness_mean": mean_or_inf(fitness_vals),
                "fitness_best": min(fitness_vals) if fitness_vals else float("inf"),
                "runtime_mean_sec": statistics.mean(runtime_vals) if runtime_vals else float("inf"),
            }
        )

    summary_csv = Path(args.outdir) / f"summary_L{level_tag}_C{comp_tag}.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance",
                "level",
                "compression_pct",
                "variant",
                "runs",
                "ok_runs",
                "timeout_runs",
                "error_runs",
                "fitness_mean",
                "fitness_best",
                "runtime_mean_sec",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    by_key = {}
    for row in summary_rows:
        key = (row["instance"], row["level"], row["compression_pct"])
        by_key.setdefault(key, {})[row["variant"]] = row

    compare_rows = []
    for key in sorted(by_key.keys()):
        instance, level, compression = key
        m = by_key[key].get("multilevel_time")
        t = by_key[key].get("pure_tabu")
        if not m or not t:
            continue
        compare_rows.append(
            {
                "instance": instance,
                "level": level,
                "compression_pct": compression,
                "multilevel_fitness_mean": m["fitness_mean"],
                "tabu_fitness_mean": t["fitness_mean"],
                "fitness_gap_tabu_minus_multi": t["fitness_mean"] - m["fitness_mean"],
                "multilevel_runtime_mean_sec": m["runtime_mean_sec"],
                "tabu_runtime_mean_sec": t["runtime_mean_sec"],
                "runtime_gap_tabu_minus_multi": t["runtime_mean_sec"] - m["runtime_mean_sec"],
            }
        )

    compare_csv = Path(args.outdir) / f"compare_L{level_tag}_C{comp_tag}.csv"
    with compare_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance",
                "level",
                "compression_pct",
                "multilevel_fitness_mean",
                "tabu_fitness_mean",
                "fitness_gap_tabu_minus_multi",
                "multilevel_runtime_mean_sec",
                "tabu_runtime_mean_sec",
                "runtime_gap_tabu_minus_multi",
            ],
        )
        writer.writeheader()
        writer.writerows(compare_rows)

    print(f"RAW={raw_csv}")
    print(f"SUMMARY={summary_csv}")
    print(f"COMPARE={compare_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
