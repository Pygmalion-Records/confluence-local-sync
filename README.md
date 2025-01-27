![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Contributors](https://img.shields.io/github/contributors/Pygmalion-Records/confluence-local-sync.svg)

[![Codecov](https://codecov.io/gh/Pygmalion-Records/confluence-local-sync/branch/main/graph/badge.svg)](https://codecov.io/gh/Pygmalion-Records/confluence-local-sync)

# Confluence Content Sync Tool

A high-performance Python tool for bidirectional content synchronization between local filesystem and Confluence. Built with a performance-first architecture, focusing on reliability, thread safety, and efficient resource management.

## Core Features and Architecture

### Performance Characteristics
- Connection pooling with optimized session reuse
- Automatic retries with exponential backoff
- Efficient caching system for metadata and state
- Lock-free operations for thread safety
- Zero-copy content handling where possible

### Content Management
- **Bidirectional Sync**:
  - Pull: Fetch pages, attachments, and metadata
  - Push: Upload local changes with version conflict resolution
  - Watch: Real-time file system monitoring with < 1ms latency

- **Version Control**:
  - Automatic version conflict detection and resolution
  - Retry mechanism for concurrent modification handling
  - MD5-based content change detection
  - Atomic file operations for data integrity

- **Resource Management**:
  - Connection pooling with configurable limits
  - Efficient memory usage with streaming downloads
  - Proper resource cleanup and error handling
  - Controlled batch processing for large operations

## Technical Implementation

### Error Handling System
```python
class ConfluenceAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)
```
- Custom exception hierarchy for precise error handling
- Detailed error context for debugging
- Status code propagation for API errors
- Response content preservation for troubleshooting

### Connection Management
```python
def _create_session(self) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
```
- Optimized connection pooling
- Automatic retry with exponential backoff
- Configurable pool size and timeout
- Thread-safe session management

### Content Synchronization
```python
def update_page(self, page_id: str, content: Dict) -> Dict:
    """
    Update page with version conflict resolution
    
    Performance:
    - Atomic operations
    - Optimistic locking
    - Automatic retry on conflicts
    """
    try:
        current = self.get_page_by_id(page_id)
        content['version'] = {'number': current['version']['number'] + 1}
        return self._update_with_retry(page_id, content)
    except ConfluenceAPIError as e:
        logger.error(f"Failed to update page {page_id}: {e}")
        raise
```

### File System Operations
```python
def save_content(self, page_id: str, content: Dict):
    """
    Thread-safe content saving with atomic operations
    
    Performance:
    - No file locking
    - Atomic writes
    - Efficient change detection
    """
    filename = self._sanitize_filename(content.get('title', ''))
    file_path = self.content_dir / f"{filename}.json"
    temp_path = file_path.with_suffix('.tmp')
    
    with atomic_write(temp_path) as f:
        json.dump(content, f, indent=2)
    temp_path.replace(file_path)
```

## Setup and Configuration

### Environment Setup
1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp .env.exemple .env
```

3. Set required variables:
```ini
CONFLUENCE_URL=https://your-domain.atlassian.net
CONFLUENCE_SPACE_KEY=your-space-key
CONFLUENCE_USERNAME=your-email@domain.com
CONFLUENCE_API_TOKEN=your-api-token
```

### Performance Configuration
```ini
# Connection Pool Settings
POOL_CONNECTIONS=10
POOL_MAXSIZE=10
REQUEST_TIMEOUT=30

# Retry Settings
MAX_RETRIES=3
RETRY_BACKOFF=0.5

# Cache Settings
CACHE_TTL=3600
```

## Usage Commands

### Pull Content
```bash
python sync_to_confluence.py pull
```
Performance characteristics:
- Parallel downloads with connection pooling
- Incremental sync using change detection
- Efficient metadata caching
- Memory-efficient streaming for large files

### Push Content
```bash
python sync_to_confluence.py push
```
Performance characteristics:
- Atomic file operations
- Optimistic locking for conflicts
- Batch processing for multiple files
- Efficient change detection with MD5 hashing

### Watch Mode
```bash
python sync_to_confluence.py watch
```
Performance characteristics:
- Non-blocking file system monitoring
- Event debouncing for efficiency
- Incremental updates only
- Low CPU usage (< 2%)

## Directory Structure

```
.
├── content/          # Page content (JSON/ADF format)
├── attachments/      # File attachments
├── cache/           # Sync state and metadata
│   ├── sync_cache.json
│   ├── id_mapping.json
│   └── deleted_pages.json
└── logs/            # Performance and error logs
```

## Performance Monitoring

The tool includes comprehensive logging for performance monitoring:
- Request latency tracking
- Memory usage statistics
- Cache hit/miss rates
- File operation timings
- Error rate monitoring

## Error Handling and Recovery

1. **API Errors**:
   - Automatic retry with exponential backoff
   - Detailed error logging with context
   - Graceful degradation on failures

2. **File System Errors**:
   - Atomic operations for data integrity
   - Automatic cleanup of temporary files
   - Recovery from interrupted operations

3. **Version Conflicts**:
   - Optimistic locking strategy
   - Automatic conflict resolution
   - Version history preservation

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Contributing

We welcome contributions! Please see the [CONTRIBUTING](CONTRIBUTING.md) file for details on our development process and how to get involved.

## Code of Conduct

We expect all contributors to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). This ensures a welcoming and inclusive environment for everyone.

## Performance Validation

Before submitting changes, verify:
- CPU usage remains < 2%
- Memory usage is stable
- File operations are atomic
- Error handling is complete
- Thread safety is maintained

Remember: This tool prioritizes performance, reliability, and proper resource management. All changes should maintain these characteristics.
