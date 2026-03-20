# Convert

uv run shapenet/mesh2brick_shapenet.py 02691156 --resolution 20 --timeout 600

# Render

uv run shapenet/render.py 02691156

# Metrics → shapenet/results/comparison_metrics.html

uv run shapenet/update_metrics.py 02691156

# Gallery → shapenet/results/gallery.html

uv run shapenet/generate_gallery.py 02691156
