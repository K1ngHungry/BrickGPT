import re
import os
import glob
from collections import defaultdict

# Paths
ASSETS_DIR = 'objaverse/assets'
HTML_OUTPUT_PATH = 'objaverse/comparison_metrics.html'

# Regex for logs
LOG_PATTERN = re.compile(r"Converting ([a-f0-9]+)\.glb.*?"
                         r"Finished in time: ([\d\.]+) s \| "
                         r"# bricks: (\d+) \| "
                         r"# connected components: (\d+) \| "
                         r"# min connected components possible: (\d+) \| "
                         r"Stability: ([\d\.]+)", re.DOTALL)

import argparse

def parse_logs(target_resolution=None):
    model_data = defaultdict(dict) # {uid: {config_name: stats}}
    all_configs = set()

    # Find all config directories
    config_dirs = glob.glob(os.path.join(ASSETS_DIR, 'res_*'))
    
    for config_dir in config_dirs:
        dir_name = os.path.basename(config_dir)
        log_path = os.path.join(config_dir, 'logs.txt')
        
        if not os.path.exists(log_path):
            continue
            
        # Beautify config name: res_20_heightpriority -> Res 20 HeightPriority
        parts = dir_name.split('_')
        try:
            resolution = int(parts[1])
        except (IndexError, ValueError):
            continue
            
        if target_resolution is not None and resolution != target_resolution:
            continue

        variant = ' '.join([p.capitalize() for p in parts[2:]])
        
        # Determine internal sort key and display name
        # We want to sort by Resolution, then by Variant order (Default < Plates < HeightPriority < Volume < Others)
        variant_rank = {
            'Default': 1,
            'Plates': 2, 
            'Heightpriority': 3,
            'Volume': 4
        }.get(variant, 99)
        
        config_obj = {
            'id': dir_name,
            'display': f"Res {resolution} {variant}",
            'sort_key': (resolution, variant_rank, variant),
            'resolution': resolution,
            'variant': variant
        }
        
        # We can't put objects in a set easily if not hashable, so lets store by id in a dict
        all_configs.add(config_obj['id'])
        
        with open(log_path, 'r') as f:
            content = f.read()
        
        matches = LOG_PATTERN.findall(content)
        for m in matches:
            uid, time, bricks, comps, min_comps, stability = m
            short_uid = uid[:8]
            
            model_data[short_uid][config_obj['id']] = {
                'time': float(time),
                'bricks': int(bricks),
                'components': int(comps),
                'min_components': int(min_comps),
                'stability': float(stability),
                'config': config_obj
            }

    # Sort configs list
    # Reconstruct objects from one of the models or just re-parse dir names? 
    # Let's just re-parse based on the collected IDs to have a sorted list of headers
    sorted_configs = []
    for cid in all_configs:
        parts = cid.split('_')
        resolution = int(parts[1])
        variant = ' '.join([p.capitalize() for p in parts[2:]])
        variant_rank = {
            'Default': 1,
            'Plates': 2, 
            'Heightpriority': 3,
            'Volume': 4
        }.get(variant, 99)
        
        sorted_configs.append({
            'id': cid,
            'display': f"Res {resolution} {variant}",
            'sort_key': (resolution, variant_rank, variant)
        })
    
    sorted_configs.sort(key=lambda x: x['sort_key'])
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
                    html += "<td>-</td>"
            html += "</tr>\n"
            
    html += """        </tbody>
    </table>

    <h2>Aggregated Totals</h2>
    <table class="summary-table">
        <thead>
            <tr>
                <th>Configuration</th>
                <th>Total Time (s)</th>
                <th>Total Bricks</th>
                <th>Avg Stability</th>
                <th>Disconnected Models</th>
            </tr>
        </thead>
        <tbody>
"""

    # Summary Table
    for conf in sorted_configs:
        cid = conf['id']
        total_time = 0
        total_bricks = 0
        total_stability = 0
        disconnected = 0
        count = 0
        
        # Only count models where this config ran
        # But for fair comparison, usually we want intersection? 
        # For now, just sum whatever ran.
        
        for uid, runs in model_data.items():
            if cid in runs:
                d = runs[cid]
                total_time += d['time']
                total_bricks += d['bricks']
                total_stability += d['stability']
                if d['components'] > d['min_components']:
                    disconnected += 1
                count += 1
        
        if count > 0:
            avg_stability = total_stability / count
            
            stab_class = ' class="good"' if avg_stability < 0.35 else ''
            disc_class = ' class="good"' if disconnected == 0 else ' class="highlight"'
            
            html += f"            <tr>"
            html += f"<td>{conf['display']}</td>"
            html += f"<td>{total_time:.2f}</td>"
            html += f"<td>{total_bricks}</td>"
            html += f"<td{stab_class}>{avg_stability:.3f}</td>"
            html += f"<td{disc_class}>{disconnected} / {count}</td>"
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
    parser.add_argument('--resolution', type=int, default=None, help='Filter by resolution (e.g., 20)')
    args = parser.parse_args()

    data, configs = parse_logs(target_resolution=args.resolution)
    html_content = generate_html(data, configs)
    
    with open(HTML_OUTPUT_PATH, 'w') as f:
        f.write(html_content)
    
    print(f"Successfully generated {HTML_OUTPUT_PATH} from {len(configs)} configurations.")
