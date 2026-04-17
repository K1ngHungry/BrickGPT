import re
import os
import glob
from collections import defaultdict

from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent.parent  # tools/analysis/ -> objaverse/
ASSETS_DIR = str(SCRIPT_DIR / 'assets')
MESHES_DIR = str(SCRIPT_DIR / 'data' / 'meshes' / 'general')
RESULTS_DIR = SCRIPT_DIR / 'results'

# Regex patterns for line-by-line parsing
CONVERTING_PATTERN = re.compile(r"Converting ([a-f0-9]+)\.glb")
SKIPPED_PATTERN = re.compile(r"SKIPPED ([a-f0-9]+)\.glb")
FINISHED_PATTERN = re.compile(r"Finished in time: ([\d\.]+) s \| "
                              r"# bricks: (\d+) \| "
                              r"# connected components: (\d+) \| "
                              r"# min connected components possible: (\d+) \| "
                              r"Stability: ([\d\.]+)")

import argparse

def parse_logs(target_resolutions=None, assets_dir=None, meshes_dir=None):
    # Use provided directories or fall back to defaults
    _assets_dir = assets_dir if assets_dir is not None else ASSETS_DIR

    model_data = defaultdict(dict) # {uid: {config_name: stats}}
    all_configs = {}  # {config_id: config_obj}

    # Pre-populate model_data with all glb files found in meshes directory (if provided)
    if meshes_dir:
        glb_files = sorted(glob.glob(os.path.join(str(meshes_dir), '*.glb')))
        for g in glb_files:
            filename = os.path.basename(g)
            uid = os.path.splitext(filename)[0]
            short_uid = uid[:8]
            # Just accessing it creates the entry in defaultdict
            _ = model_data[short_uid]

    # Look for logs.txt directly in assets_dir
    log_path = os.path.join(str(_assets_dir), 'logs.txt')

    if os.path.exists(log_path):
        # Extract configuration info from directory name
        dir_name = Path(_assets_dir).name

        # Parse directory name for resolution and variant
        # Examples: mesh_results, mesh_res_20, res_20_baseline, general_20, general_32, etc.
        if 'res_' in dir_name.lower():
            parts = dir_name.lower().split('_')
            res_idx = parts.index('res') if 'res' in parts else parts.index([p for p in parts if 'res' in p][0].replace('res', ''))
            if res_idx + 1 < len(parts):
                try:
                    resolution = int(parts[res_idx + 1])
                except ValueError:
                    resolution = 20
            else:
                resolution = 20

            # Check for variant name
            if len(parts) > res_idx + 2:
                variant = ' '.join([p.capitalize() for p in parts[res_idx + 2:]])
            else:
                variant = ''
        elif 'mesh_results' in dir_name:
            resolution = 32
            variant = 'Slopes'
        elif '_' in dir_name:
            # Handle patterns like "general_20", "buildings_32"
            parts = dir_name.split('_')
            if parts[-1].isdigit():
                resolution = int(parts[-1])
                variant = '_'.join(parts[:-1]).capitalize()
            else:
                resolution = 20
                variant = dir_name.capitalize()
        else:
            resolution = 20
            variant = dir_name.capitalize()

        config_obj = {
            'id': dir_name,
            'display': f"{variant} (Res {resolution})" if variant else f"Res {resolution}",
            'sort_key': (resolution, 0, variant),
            'resolution': resolution,
            'variant': variant
        }

        all_configs[config_obj['id']] = config_obj

        with open(log_path, 'r') as f:
            lines = f.readlines()

        # Line-by-line parsing with state tracking
        current_uid = None
        for line in lines:
            # Check for new conversion start
            conv_match = CONVERTING_PATTERN.search(line)
            if conv_match:
                current_uid = conv_match.group(1)
                continue

            # Check if current model was skipped - reset state
            skip_match = SKIPPED_PATTERN.search(line)
            if skip_match:
                current_uid = None
                continue

            # Check for finished line - only process if we have a valid current_uid
            fin_match = FINISHED_PATTERN.search(line)
            if fin_match and current_uid:
                time_val, bricks, comps, min_comps, stability = fin_match.groups()
                short_uid = current_uid[:8]

                model_data[short_uid][config_obj['id']] = {
                    'time': float(time_val),
                    'bricks': int(bricks),
                    'components': int(comps),
                    'min_components': int(min_comps),
                    'stability': float(stability),
                    'config': config_obj
                }
                current_uid = None  # Reset after successful match

    # Sort configs list using the stored config objects
    sorted_configs = sorted(all_configs.values(), key=lambda x: x['sort_key'])
    return model_data, sorted_configs

def generate_html(model_data, sorted_configs):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BrickGPT Metric Comparison</title>
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

    <h1>Comparison Metrics</h1>

    <table>
        <thead>
            <tr>
                <th>Model ID / Metric</th>
"""
    # Header Row
    for conf in sorted_configs:
        html += f"                <th>{conf['display']}</th>\n"
    
    html += """            </tr>
        </thead>
        <tbody>
"""

    # Body
    for uid, runs in model_data.items():
        # Title Row
        html += f'            <tr class="model-header"><td colspan="{len(sorted_configs) + 1}">{uid}</td></tr>\n'
        
        # Metrics Rows
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
                    
                    # Formatting logic
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

    # Collect per-config stats for both tables
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

    # Summary Table (all models)
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

    # Stable & connected only table
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
    parser = argparse.ArgumentParser(description='Generate comparison metrics HTML.')
    parser.add_argument('-a', '--assets-dir', type=str, nargs='+', default=None, help='Assets directory/directories containing logs.txt')
    parser.add_argument('-m', '--meshes-dir', type=str, default=None, help='Directory containing .glb mesh files (optional: shows all models including failed)')
    parser.add_argument('-o', '--output', type=str, default=None, help='Output path (.html file) or directory (default: results/comparison_metrics.html)')
    parser.add_argument('-r', '--resolutions', nargs='+', type=int, default=None, help='Filter by specific resolutions (e.g., 20 50)')
    parser.add_argument('-c', '--compare', action='store_true', help='Compare mode: requires at least 2 --assets-dir paths')
    args = parser.parse_args()

    # Set directories from args or use defaults
    meshes_dir = Path(args.meshes_dir).resolve() if args.meshes_dir else None

    # Handle output path - can be directory or full file path
    if args.output:
        output_arg = Path(args.output).resolve()
        if args.output.endswith('.html'):
            # Treat as full file path
            output_path = str(output_arg)
            output_arg.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Treat as directory
            output_arg.mkdir(parents=True, exist_ok=True)
            output_path = str(output_arg / 'comparison_metrics.html')
    else:
        # Use default
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(RESULTS_DIR / 'comparison_metrics.html')

    # Handle compare mode with multiple assets directories
    if args.compare:
        if not args.assets_dir or len(args.assets_dir) < 2:
            parser.error("-c/--compare requires at least 2 --assets-dir paths")

        # Merge data from multiple directories
        merged_data = defaultdict(dict)
        all_configs = []

        for asset_path in args.assets_dir:
            asset_dir = Path(asset_path).resolve()
            data, configs = parse_logs(
                target_resolutions=args.resolutions,
                assets_dir=asset_dir,
                meshes_dir=meshes_dir
            )

            # Merge model data
            for uid, runs in data.items():
                merged_data[uid].update(runs)

            # Collect all configs
            all_configs.extend(configs)

        # Sort configs by resolution
        all_configs.sort(key=lambda x: x['sort_key'])
        html_content = generate_html(merged_data, all_configs)
    else:
        # Single directory mode
        assets_dir = Path(args.assets_dir[0]).resolve() if args.assets_dir else ASSETS_DIR
        data, configs = parse_logs(
            target_resolutions=args.resolutions,
            assets_dir=assets_dir,
            meshes_dir=meshes_dir
        )
        html_content = generate_html(data, configs)

    with open(output_path, 'w') as f:
        f.write(html_content)

    print(f"Successfully generated {output_path} with {len(html_content)} characters.")
