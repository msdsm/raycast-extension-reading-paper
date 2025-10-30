#!/usr/bin/env python3
"""
Video conversion script to convert MOV to GIF and reduce duration to 1/2 with lower resolution
"""

import subprocess
import sys
import os
from pathlib import Path


def check_ffmpeg():
    """Check if FFmpeg is installed"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_video_duration(input_file):
    """Get video duration in seconds"""
    try:
        result = subprocess.run([
            'ffprobe', 
            '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(input_file)
        ], capture_output=True, text=True, check=True)
        
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        print("Warning: Could not determine video duration")
        return None


def get_video_info(input_file):
    """Get video resolution and other info"""
    try:
        result = subprocess.run([
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            str(input_file)
        ], capture_output=True, text=True, check=True)
        
        width, height = map(int, result.stdout.strip().split(','))
        return width, height
    except (subprocess.CalledProcessError, ValueError):
        return None, None


def convert_video_to_gif(input_file, output_file, speed_factor=2.0, target_width=800, fps=15):
    """
    Convert MOV to GIF, speed up by the given factor, and reduce resolution
    
    Args:
        input_file (Path): Input MOV file path
        output_file (Path): Output GIF file path
        speed_factor (float): Speed multiplication factor (2.0 = 2x faster = 1/2 duration)
        target_width (int): Target width for resolution scaling
        fps (int): Target frame rate for GIF
    """
    
    # Get original video info
    orig_width, orig_height = get_video_info(input_file)
    
    # Calculate target height maintaining aspect ratio
    if orig_width and orig_height:
        aspect_ratio = orig_height / orig_width
        target_height = int(target_width * aspect_ratio)
        # Ensure height is even (required for some codecs)
        if target_height % 2 == 1:
            target_height += 1
            
        print(f"Original resolution: {orig_width}x{orig_height}")
        print(f"Target resolution: {target_width}x{target_height}")
    else:
        target_width = 800
        target_height = 600
        print(f"Could not detect original resolution, using default: {target_width}x{target_height}")
    
    # Create high-quality GIF with palette optimization
    # Step 1: Generate palette
    palette_file = output_file.parent / 'palette.png'
    
    palette_cmd = [
        'ffmpeg',
        '-i', str(input_file),
        '-vf', f'fps={fps},scale={target_width}:{target_height}:flags=lanczos,setpts={1/speed_factor}*PTS,palettegen=stats_mode=diff',
        '-y',
        str(palette_file)
    ]
    
    # Step 2: Generate GIF using the palette
    gif_cmd = [
        'ffmpeg',
        '-i', str(input_file),
        '-i', str(palette_file),
        '-lavfi', f'fps={fps},scale={target_width}:{target_height}:flags=lanczos,setpts={1/speed_factor}*PTS[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle',
        '-y',
        str(output_file)
    ]
    
    print(f"Converting {input_file} to {output_file}...")
    print(f"Speed factor: {speed_factor}x (duration will be {1/speed_factor:.2%} of original)")
    print(f"Target FPS: {fps}")
    
    try:
        # Step 1: Generate palette
        print("Step 1: Generating color palette...")
        subprocess.run(palette_cmd, check=True, capture_output=True)
        
        # Step 2: Generate GIF
        print("Step 2: Converting to GIF...")
        subprocess.run(gif_cmd, check=True, capture_output=False)
        
        # Clean up palette file
        if palette_file.exists():
            palette_file.unlink()
        
        print(f"✅ Conversion completed successfully!")
        print(f"Output file: {output_file}")
        
        # Get file sizes for comparison
        input_size = input_file.stat().st_size / (1024 * 1024)  # MB
        output_size = output_file.stat().st_size / (1024 * 1024)  # MB
        
        print(f"Input file size: {input_size:.2f} MB")
        print(f"Output file size: {output_size:.2f} MB")
        if input_size > 0:
            print(f"Size reduction: {(1 - output_size/input_size)*100:.1f}%")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during conversion: {e}")
        # Clean up palette file if it exists
        if palette_file.exists():
            palette_file.unlink()
        return False


def main():
    """Main function"""
    # Set up file paths - using current directory
    current_dir = Path.cwd()
    input_file = current_dir / 'results.mp4'
    output_file = current_dir / 'results.gif'
    
    # Check if input file exists
    if not input_file.exists():
        print(f"❌ Error: Input file not found: {input_file}")
        sys.exit(1)
    
    # Check if FFmpeg is available
    if not check_ffmpeg():
        print("❌ Error: FFmpeg is not installed or not available in PATH")
        print("Please install FFmpeg:")
        print("  macOS: brew install ffmpeg")
        print("  Ubuntu/Debian: sudo apt install ffmpeg")
        print("  Windows: Download from https://ffmpeg.org/")
        sys.exit(1)
    
    # Get original video duration
    original_duration = get_video_duration(input_file)
    if original_duration:
        new_duration = original_duration / 2.0
        print(f"Original duration: {original_duration:.2f} seconds")
        print(f"New duration: {new_duration:.2f} seconds")
    
    # Perform conversion with 2x speed and GIF format
    success = convert_video_to_gif(input_file, output_file, speed_factor=2.0, target_width=800, fps=15)
    
    if success:
        print(f"🎉 Video conversion completed!")
        print(f"You can now use {output_file} in your README.md")
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()