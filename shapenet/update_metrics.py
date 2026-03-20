import re
import os
import argparse
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets"
RESULTS_DIR = SCRIPT_DIR / "results"

# Regex patterns (same format as objaverse pipeline)
CONVERTING_PATTERN = re.compile(r"Converting ([a-f0-9]+)\.glb")
SKIPPED_PATTERN = re.compile(r"SKIPPED ([a-f0-9]+)\.glb")
FINISHED_PATTERN = re.compile(r"Finished in time: ([\d\.]+) s \| "
                              r"# bricks: (\d+) \| "
                              r"# connected components: (\d+) \| "
                              r"# min connected components possible: (\d+) \| "
                              r"Stability: ([\d\.]+)")


def parse_logs(input_dir, target_resolutions=None):
    input_path = Path(input_dir)
    model_data = defaultdict(dict)
    all_configs = {}

    # Find all res_* directories
    config_dirs = sorted(input_path.glob("res_*"))

    for config_dir in config_dirs:
        dir_name = config_dir.name
        log_path = config_dir / "logs.txt"

        if not log_path.exists():
            continue

        parts = dir_name.split('_')
        try:
            resolution = int(parts[1])
        except (IndexError, ValueError):
            continue

        if target_resolutions is not None and resolution not in target_resolutions:
            continue

        variant = ' '.join([p.capitalize() for p in parts[2:]]) if len(parts) > 2 else 'Default'

        config_obj = {
            'id': dir_name,
            'display': f"Res {resolution}" + (f" {variant}" if variant != 'Default' else ''),
            'sort_key': (resolution, variant),
            'resolution': resolution,
        }
        all_configs[dir_name] = config_obj

        with open(log_path, 'r') as f:
            lines = f.readlines()

        current_uid = None
        for line in lines:
            conv_match = CONVERTING_PATTERN.search(line)
            if conv_match:
                current_uid = conv_match.group(1)
                continue

            skip_match = SKIPPED_PATTERN.search(line)
            if skip_match:
                current_uid = None
                continue

            fin_match = FINISHED_PATTERN.search(line)
            if fin_match and current_uid:
                time_val, bricks, comps, min_comps, stability = fin_match.groups()
                short_uid = current_uid[:8]

                model_data[short_uid][dir_name] = {
                    'uid': current_uid,
                    'time': float(time_val),
                    'bricks': int(bricks),
                    'components': int(comps),
                    'min_components': int(min_comps),
                    'stability': float(stability),
                    'config': config_obj,
                }
                current_uid = None

    sorted_configs = sorted(all_configs.values(), key=lambda x: x['sort_key'])
    return model_data, sorted_configs


def generate_html(model_data, sorted_configs):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ShapeNet Metric Comparison</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; max-width: 100%; margin: 0 auto; background-color: #f4f4f9; }
        h1, h2 { color: #333; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 30px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 8px; font-size: 14px; }
        th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #eee; }
        th { background-color: #007bff; color: white; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.05em; white-space: nowrap; position: sticky; top: 0; z-index: 10; }
        tr:last-child td { border-bottom: none; }
        tr:nth-child(even) { background-color: #f8f9fa; }
        .model-header { background-color: #e9ecef; font-weight: bold; color: #495057; text-align: center; }
        .summary-table th { background-color: #28a745; }
        .highlight { font-weight: bold; color: #dc3545; }
        .good { color: #28a745; font-weight: bold; }
        .metric-label { font-weight: 500; color: #555; background-color: #fff; width: 120px; }
    </style>
</head>
<body>

    <h1>ShapeNet Comparison Metrics</h1>

    <table>
        <thead>
            <tr>
                <th>Model ID / Metric</th>
"""
    for conf in sorted_configs:
        html += f"                <th>{conf['display']}</th>\n"

    html += """            </tr>
        </thead>
        <tbody>
"""

    for uid, runs in model_data.items():
        html += f'            <tr class="model-header"><td colspan="{len(sorted_configs) + 1}">{uid}</td></tr>\n'

        metrics_order = [
            ('Time (s)', 'time'),
            ('Bricks', 'bricks'),
            ('Components', 'components'),
            ('Min Components', 'min_components'),
            ('Stability', 'stability')
        ]

        for label, key in metrics_order:
            html += f"            <tr><td class='metric-label'>{label}</td>"
            for conf in sorted_configs:
                cid = conf['id']
                if cid in runs:
                    val = runs[cid][key]
                    css_class = ""

                    if key == 'components':
                        if runs[cid]['min_components'] == val:
                            css_class = ' class="good"'
                        else:
                            css_class = ' class="highlight"'
                    elif key == 'stability':
                        if val > 0.99: css_class = ' class="highlight"'
                        elif val < 0.35: css_class = ' class="good"'
                        val = f"{val:.3f}"
                    elif key == 'time':
                        val = f"{val:.2f}"

                    html += f"<td{css_class}>{val}</td>"
                else:
                    html += "<td></td>"
            html += "</tr>\n"

    html += """        </tbody>
    </table>

    <h2>Aggregated Totals</h2>
    <table class="summary-table">
        <thead>
            <tr>
                <th>Configuration</th>
                <th>Avg Time (s)</th>
                <th>Avg Bricks</th>
                <th>Avg Stability</th>
                <th>Unstable Models</th>
                <th>Disconnected Models</th>
            </tr>
        </thead>
        <tbody>
"""

    config_stats = []
    for conf in sorted_configs:
        cid = conf['id']
        total_time = 0
        stable_only_time = 0
        total_bricks = 0
        stable_only_bricks = 0
        total_stability = 0
        stable_only_stability = 0
        disconnected = 0
        unstable = 0
        stable_count = 0
        count = 0

        for uid, runs in model_data.items():
            if cid in runs:
                d = runs[cid]
                total_time += d['time']
                total_bricks += d['bricks']
                total_stability += d['stability']
                if d['stability'] >= 1.0:
                    unstable += 1
                else:
                    stable_only_time += d['time']
                    stable_only_bricks += d['bricks']
                    stable_only_stability += d['stability']
                    stable_count += 1
                if d['components'] > d['min_components']:
                    disconnected += 1
                count += 1

        config_stats.append({
            'conf': conf, 'count': count, 'total_time': total_time,
            'total_bricks': total_bricks, 'stable_only_bricks': stable_only_bricks,
            'total_stability': total_stability,
            'stable_only_time': stable_only_time, 'stable_only_stability': stable_only_stability,
            'stable_count': stable_count, 'unstable': unstable, 'disconnected': disconnected
        })

    for s in config_stats:
        if s['count'] > 0:
            avg_time = s['total_time'] / s['count']
            avg_stability = s['total_stability'] / s['count']

            stab_class = ' class="good"' if avg_stability < 0.35 else ''
            unstable_class = ' class="good"' if s['unstable'] == 0 else ' class="highlight"'
            disc_class = ' class="good"' if s['disconnected'] == 0 else ' class="highlight"'

            html += f"            <tr>"
            html += f"<td>{s['conf']['display']}</td>"
            avg_bricks = s['total_bricks'] / s['count']
            html += f"<td>{avg_time:.2f}</td>"
            html += f"<td>{avg_bricks:.0f}</td>"
            html += f"<td{stab_class}>{avg_stability:.3f}</td>"
            html += f"<td{unstable_class}>{s['unstable']} / {s['count']}</td>"
            html += f"<td{disc_class}>{s['disconnected']} / {s['count']}</td>"
            html += "</tr>\n"

    html += """        </tbody>
    </table>

    <h2>Aggregated Totals (Stable &amp; Connected Only)</h2>
    <table class="summary-table">
        <thead>
            <tr>
                <th>Configuration</th>
                <th>Avg Time (s)</th>
                <th>Avg Bricks</th>
                <th>Avg Stability</th>
                <th>Models Included</th>
            </tr>
        </thead>
        <tbody>
"""

    for s in config_stats:
        if s['stable_count'] > 0:
            avg_time = s['stable_only_time'] / s['stable_count']
            avg_stability = s['stable_only_stability'] / s['stable_count']

            stab_class = ' class="good"' if avg_stability < 0.35 else ''

            html += f"            <tr>"
            html += f"<td>{s['conf']['display']}</td>"
            avg_bricks = s['stable_only_bricks'] / s['stable_count']
            html += f"<td>{avg_time:.2f}</td>"
            html += f"<td>{avg_bricks:.0f}</td>"
            html += f"<td{stab_class}>{avg_stability:.3f}</td>"
            html += f"<td>{s['stable_count']} / {s['count']}</td>"
            html += "</tr>\n"

    html += """        </tbody>
    </table>

    <p><em>Note: Stability values of 1.0 indicate instability/disconnection. Lower stability score is better rigidity.</em></p>

</body>
</html>
"""
    return html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate ShapeNet comparison metrics HTML.')
    parser.add_argument('category', type=str, help='ShapeNet category ID (e.g. 02691156)')
    parser.add_argument('--resolutions', nargs='+', type=int, default=None, help='Filter by specific resolutions')
    parser.add_argument('-o', '--output', type=str, default=None, help='Output HTML file path')
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output if args.output else str(RESULTS_DIR / 'comparison_metrics.html')

    data, configs = parse_logs(str(ASSETS_DIR / args.category), target_resolutions=args.resolutions)
    html_content = generate_html(data, configs)

    with open(output_path, 'w') as f:
        f.write(html_content)

    print(f"Generated {output_path} from {len(configs)} configurations, {len(data)} models.")
