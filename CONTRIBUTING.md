# Contributing to Confluence Content Sync Tool

We love your input! We want to make contributing to this tool as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## Development Process

We use GitHub to host code, to track issues and feature requests, as well as accept pull requests.

1. Fork the repo and create your branch from `main`
2. If you've added code that should be tested, add tests
3. If you've changed APIs, update the documentation
4. Ensure the test suite passes
5. Make sure your code meets our performance requirements
6. Issue that pull request!

## Performance Requirements

All contributions must maintain our performance-first architecture:

1. **Latency Requirements**:
   - File operations must complete in < 1ms
   - API operations must handle timeouts gracefully
   - Watch mode must maintain < 2% CPU usage

2. **Resource Management**:
   - No unnecessary memory allocations
   - Proper resource cleanup
   - Efficient connection pooling

3. **Thread Safety**:
   - Use lock-free operations where possible
   - Implement proper synchronization when needed
   - Maintain atomic file operations

## Code Style and Standards

1. **Python Code Style**:
   - Follow PEP 8
   - Use type hints
   - Document all public APIs
   - Keep functions focused and small

2. **Documentation**:
   - Update README.md for feature changes
   - Include performance characteristics
   - Document error handling
   - Provide usage examples

3. **Testing**:
   - Write unit tests for new features
   - Include performance tests
   - Test error conditions
   - Verify thread safety

## License

By contributing, you agree that your contributions will be licensed under its MIT License.

## References

* [Python PEP 8](https://www.python.org/dev/peps/pep-0008/)
* [Atlassian API Documentation](https://developer.atlassian.com/cloud/confluence/rest/)
