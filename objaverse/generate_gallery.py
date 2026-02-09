
import os
import sys
import argparse
from pathlib import Path

# Enhance sys.path to allow importing from the same directory
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.append(str(SCRIPT_DIR))

try:
    from update_metrics import parse_logs
except ImportError:
    # Fallback if running from root without package structure
    pass

ASSETS_DIR = SCRIPT_DIR / "assets"
HTML_OUTPUT = SCRIPT_DIR / "gallery.html"

def generate_html(models, configs, model_stats, output_dir):
    """
    Generates the HTML gallery.
    models: { 'uid': {'glb': path, 'renders': {config_id: png_path}} }
    configs: List of config dicts from parse_logs [{'id': 'res_20_plates', 'display': '...', ...}]
    model_stats: Dict of stats from parse_logs {short_uid: {config_id: {time, bricks, ...}}}
    output_dir: Path object for the directory where HTML is saved (for relative paths)
    """

    col_count = 1 + len(configs)

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BrickGPT: Comparison Gallery</title>
    <script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f0f2f5; padding: 20px; color: #333; }}
        h1 {{ text-align: center; margin-bottom: 40px; color: #1a1a1a; }}

        .model-section {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.06);
            margin-bottom: 40px;
            overflow: visible;
            padding: 0;
            border: 1px solid #e0e0e0;
        }}

        .model-header {{
            background: #2c3e50;
            color: white;
            padding: 15px 25px;
            font-size: 1.1em;
            font-weight: 500;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        .comparison-grid {{
            display: grid;
            grid-template-columns: repeat({col_count}, 1fr);
            gap: 0;
        }}

        .grid-item {{
            border-right: 1px solid #eee;
            position: relative;
            background: #fff;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            min-height: 300px;
        }}

        .grid-item:last-child {{ border-right: none; }}

        .col-header {{
            background: #f8f9fa;
            border-bottom: 1px solid #eee;
            padding: 10px;
            text-align: center;
            font-weight: 600;
            font-size: 0.9em;
            color: #555;
        }}

        .viewport {{
            flex-grow: 1;
            position: relative;
            width: 100%;
            height: 250px; /* Fixed height for visuals */
            display: flex;
            align-items: center;
            justify-content: center;
            background: #fcfcfc;
        }}

        model-viewer {{ width: 100%; height: 100%; }}
        img {{ max-width: 95%; max-height: 95%; object-fit: contain; }}

        .stats-overlay {{
            padding: 10px;
            background: #fff;
            border-top: 1px solid #eee;
            font-size: 0.85em;
            color: #666;
        }}

        .stat-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 2px;
        }}
        .stat-label {{ color: #999; }}
        .stat-val {{ font-weight: 500; color: #333; }}
        .stat-val.good {{ color: #28a745; }}
        .stat-val.bad {{ color: #dc3545; }}

        .missing-placeholder {{
            color: #ccc;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <h1>Objaverse vs LEGO Resolution Comparison</h1>

    <div class="comparison-grid" style="margin-bottom: 20px; border-radius: 8px; overflow: hidden; border: 1px solid #ddd;">
        <div class="col-header">Original (GLB)</div>
        { "".join(f'<div class="col-header">{c["display"]}</div>' for c in configs) }
    </div>
    """

    for uid, data in models.items():
        glb_rel = os.path.relpath(data['glb'], output_dir)
        short_uid = uid[:8]

        html_content += f"""
        <div class="model-section">
            <div class="model-header">
                <span>Model: {uid}</span>
            </div>
            <div class="comparison-grid">
                <!-- 1. Original 3D Model -->
                <div class="grid-item">
                    <div class="viewport">
                        <model-viewer
                            src="{glb_rel}"
                            auto-rotate camera-controls
                            shadow-intensity="1"
                            interaction-prompt="none">
                        </model-viewer>
                    </div>
                    <div class="stats-overlay">
                        <div class="stat-row">
                            <span class="stat-label">UID</span>
                            <span class="stat-val">{short_uid}</span>
                        </div>
                    </div>
                </div>
        """

        # 2. Render Columns (Sorted)
        for conf in configs:
            cid = conf['id']
            png_path = data['renders'].get(cid)

            # Get stats
            stats = model_stats.get(short_uid, {}).get(cid, None)

            if png_path:
                png_rel = os.path.relpath(png_path, output_dir)
                visual = f'<img src="{png_rel}" alt="{conf["display"]}">'
            else:
                visual = '<span class="missing-placeholder">No Render</span>'

            stats_html = ""
            if stats:
                is_disconnected = stats['components'] > stats['min_components']
                conn_class = "bad" if is_disconnected else "good"
                stab = stats['stability']
                stab_class = "good" if stab < 0.35 else ("bad" if stab > 0.9 else "")

                stats_html = f"""
                <div class="stat-row"><span class="stat-label">Time</span><span class="stat-val">{stats['time']:.2f}s</span></div>
                <div class="stat-row"><span class="stat-label">Bricks</span><span class="stat-val">{stats['bricks']}</span></div>
                <div class="stat-row"><span class="stat-label">Conn</span><span class="stat-val {conn_class}">{stats['components']}/{stats['min_components']}</span></div>
                <div class="stat-row"><span class="stat-label">Stab</span><span class="stat-val {stab_class}">{stab:.3f}</span></div>
                """
            else:
                stats_html = '<div class="stat-row" style="justify-content:center; color:#ccc;">No Data</div>'

            html_content += f"""
                <div class="grid-item">
                    <div class="viewport">
                        {visual}
                    </div>
                    <div class="stats-overlay">
                        {stats_html}
                    </div>
                </div>
            """

        html_content += """
            </div>
        </div>
        """

    html_content += """
    <footer style="text-align: center; margin-top: 50px; color: #888;">
        Generated by BrickGPT
    </footer>
</body>
</html>
    """

    return html_content

def main():
    parser = argparse.ArgumentParser(description='Generate comparison gallery.')
    parser.add_argument('--resolutions', nargs='+', type=int, default=None, help='Filter by specific resolutions (e.g., 20 50)')
    parser.add_argument('-o', '--output', type=str, default=None, help='Output HTML file path. Defaults to gallery.html in script directory.')
    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = SCRIPT_DIR / "gallery.html"

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if not ASSETS_DIR.exists():
        print(f"Error: assets directory not found at {ASSETS_DIR}")
        return

    # 1. Get Metrics and Configs using update_metrics logic
    print("Parsing logs...")
    # Make sure we can import
    try:
        from update_metrics import parse_logs
    except ImportError:
        print("Error: Could not import parse_logs from update_metrics.py. Make sure you are running from the project root or objaverse directory.")
        return

    model_stats, configs = parse_logs(target_resolutions=args.resolutions)

    # 2. Build Models Dict (GLB + Renders)
    # models = { 'uid': { 'glb': path, 'renders': {config_id: png_path} } }
    models = {}

    # Find GLBs
    glb_files = list(ASSETS_DIR.glob("*.glb"))
    print(f"Found {len(glb_files)} source GLB files.")
    for glb in glb_files:
        uid = glb.stem
        models[uid] = {'glb': glb, 'renders': {}}

    # Find Renders for each config
    for conf in configs:
        cid = conf['id']
        conf_dir = ASSETS_DIR / cid
        if not conf_dir.exists():
            continue

        png_files = list(conf_dir.glob("*.png"))
        for png in png_files:
            uid = png.stem
            if uid in models:
                models[uid]['renders'][cid] = png

    # 3. Generate Gallery
    print(f"Generating gallery for {len(models)} models across {len(configs)} configurations...")
    html = generate_html(models, configs, model_stats, output_dir)

    with open(output_path, "w") as f:
        f.write(html)

    print(f"Gallery generated: {output_path}")

if __name__ == "__main__":
    main()
