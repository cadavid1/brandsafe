"""
Logging utilities for UXR CUJ Analysis
"""

import logging
from pathlib import Path
from datetime import datetime


# Create logs directory
LOG_DIR = Path("./data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
LOG_FILE = LOG_DIR / f"uxr_mate_{datetime.now().strftime('%Y%m%d')}.log"

# Create logger
logger = logging.getLogger("uxr_mate")
logger.setLevel(logging.INFO)

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)

# Console handler (for errors only)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)

# Formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def log_info(message: str):
    """Log info message"""
    logger.info(message)


def log_error(message: str, exc_info=None):
    """Log error message"""
    if exc_info:
        logger.error(message, exc_info=exc_info)
    else:
        logger.error(message)


def log_warning(message: str):
    """Log warning message"""
    logger.warning(message)


def log_video_upload(video_name: str, file_size_mb: float, duration_seconds: float):
    """Log video upload"""
    log_info(f"Video uploaded: {video_name} ({file_size_mb:.1f}MB, {duration_seconds:.1f}s)")


def log_analysis_start(cuj_id: str, video_name: str, model: str):
    """Log analysis start"""
    log_info(f"Analysis started: CUJ={cuj_id}, Video={video_name}, Model={model}")


def log_analysis_complete(cuj_id: str, status: str, friction_score: int, cost: float):
    """Log analysis completion"""
    log_info(f"Analysis complete: CUJ={cuj_id}, Status={status}, Friction={friction_score}, Cost=${cost:.4f}")


def log_analysis_error(cuj_id: str, error: str):
    """Log analysis error"""
    log_error(f"Analysis failed: CUJ={cuj_id}, Error={error}")


def log_export(format: str, filepath: str):
    """Log data export"""
    log_info(f"Exported results: Format={format}, File={filepath}")
