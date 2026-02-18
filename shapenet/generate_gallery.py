import os
import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = SCRIPT_DIR / "assets"
RESULTS_DIR = SCRIPT_DIR / "results"

sys.path.append(str(SCRIPT_DIR))
from update_metrics import parse_logs


def generate_html(models, configs, model_stats, output_dir):
    col_count = 1 + len(configs)

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ShapeNet: Comparison Gallery</title>
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
            height: 250px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #fcfcfc;
        }}

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

        .viewport img {{ cursor: pointer; }}
        .lightbox {{
            display: none; position: fixed; top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 9999; align-items: center; justify-content: center; cursor: pointer;
        }}
        .lightbox.active {{ display: flex; }}
        .lightbox img {{ max-width: 90vw; max-height: 90vh; object-fit: contain; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="lightbox" onclick="this.classList.remove('active')"><img id="lightbox-img" src="" alt=""></div>
    <h1>ShapeNet LEGO Comparison Gallery</h1>

    <div class="comparison-grid" style="margin-bottom: 20px; border-radius: 8px; overflow: hidden; border: 1px solid #ddd;">
        <div class="col-header">Original (StableLego)</div>
        { "".join(f'<div class="col-header">{c["display"]}</div>' for c in configs) }
    </div>
    """

    for uid, data in models.items():
        short_uid = uid[:8]

        # Original image
        vis_path = data.get('vis')
        if vis_path:
            vis_rel = os.path.relpath(vis_path, output_dir)
            orig_visual = f'<img src="{vis_rel}" alt="Original">'
        else:
            orig_visual = '<span class="missing-placeholder">No Image</span>'

        html_content += f"""
        <div class="model-section">
            <div class="model-header">
                <span>Model: {uid}</span>
            </div>
            <div class="comparison-grid">
                <div class="grid-item">
                    <div class="viewport">
                        {orig_visual}
                    </div>
                    <div class="stats-overlay">
                        <div class="stat-row">
                            <span class="stat-label">UID</span>
                            <span class="stat-val">{short_uid}</span>
                        </div>
                    </div>
                </div>
        """

        for conf in configs:
            cid = conf['id']
            stats = model_stats.get(short_uid, {}).get(cid, None)

            # Check for render PNG in config dir
            png_path = data['renders'].get(cid)
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
    <script>
    document.querySelectorAll('.viewport img').forEach(function(img) {
        img.addEventListener('click', function() {
            var lb = document.querySelector('.lightbox');
            document.getElementById('lightbox-img').src = img.src;
            lb.classList.add('active');
        });
    });
    </script>
    <footer style="text-align: center; margin-top: 50px; color: #888;">
        Generated by BrickGPT
    </footer>
</body>
</html>
    """

    return html_content


def main():
    parser = argparse.ArgumentParser(description='Generate ShapeNet comparison gallery.')
    parser.add_argument('category', type=str, help='ShapeNet category ID (e.g. 02691156)')
    parser.add_argument('--resolutions', nargs='+', type=int, default=None, help='Filter by specific resolutions')
    parser.add_argument('-o', '--output', type=str, default=None, help='Output HTML file path')
    args = parser.parse_args()

    input_path = ASSETS_DIR / args.category

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = RESULTS_DIR / "gallery.html"

    output_dir = output_path.parent

    # Parse logs
    model_stats, configs = parse_logs(str(input_path), target_resolutions=args.resolutions)

    # Build models dict
    models = {}
    for model_dir in sorted(input_path.iterdir()):
        if not model_dir.is_dir() or model_dir.name.startswith('res_'):
            continue
        uid = model_dir.name
        vis = model_dir / "models" / "vis.png"
        if not vis.exists():
            vis = None
        models[uid] = {'vis': vis, 'renders': {}}

    # Find render PNGs in config dirs
    for conf in configs:
        cid = conf['id']
        conf_dir = input_path / cid
        if not conf_dir.exists():
            continue
        for png in conf_dir.glob("*.png"):
            uid = png.stem
            if uid in models:
                models[uid]['renders'][cid] = png

    print(f"Generating gallery for {len(models)} models across {len(configs)} configurations...")
    html = generate_html(models, configs, model_stats, output_dir)

    with open(output_path, "w") as f:
        f.write(html)

    print(f"Gallery generated: {output_path}")


if __name__ == "__main__":
    main()
