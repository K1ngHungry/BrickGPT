
import objaverse
import pandas as pd
import os
import multiprocessing
import shutil

def download_objaverse_assets(csv_path: str, output_dir: str = "assets", max_count: int = 15):
    """
    Downloads Objaverse assets specified in a CSV file.

    Args:
        csv_path: Path to the CSV file containing UIDs.
        output_dir: Directory to save the downloaded assets.
        max_count: Maximum number of models to download (default: None, downloads all).
    """

    # Read the CSV to get the UIDs
    df = pd.read_csv(csv_path)
    uids = df["UID"].tolist()
    print(f"Found {len(uids)} UIDs in CSV.")

    # Limit to max_count if specified
    if max_count is not None:
        uids = uids[:max_count]
        print(f"Limiting download to {len(uids)} models.")

    # Create the output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")
    
    # Use multiprocessing to download in parallel
    objects = objaverse.load_objects(
        uids=uids,
        download_processes=multiprocessing.cpu_count()
    )
    
    print("\nDownload complete!")
    print("-" * 30)
    
    for uid, path in objects.items():
        # Getting file name and extension:
        filename = os.path.basename(path)
        extension = os.path.splitext(path)[1]
        dest_path = os.path.join(output_dir, f"{uid}{extension}")
        
        # Copying file to local directory for easier access
        shutil.copy2(path, dest_path)
        print(f"Saved: {dest_path}")

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Objaverse assets from a CSV file.")
    parser.add_argument("-c", "--csv", required=True, help="Path to the CSV file containing UIDs")
    parser.add_argument("-n", "--max-count", type=int, default=None, help="Maximum number of models to download (default: no limit)")
    parser.add_argument("-o", "--output-dir", default="assets", help="Directory to save downloaded assets (default: assets)")

    args = parser.parse_args()

    # Resolve paths relative to current working directory or absolute paths
    csv_file_path = os.path.abspath(args.csv)
    output_directory = os.path.abspath(args.output_dir)

    download_objaverse_assets(csv_file_path, output_directory, max_count=args.max_count)
