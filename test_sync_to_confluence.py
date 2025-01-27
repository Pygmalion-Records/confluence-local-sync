import os
import unittest
from unittest.mock import patch, MagicMock, call
from sync_to_confluence import ConfluenceAPI, ConfluenceAPIError, LocalContentManager, ContentSyncer, ContentChangeHandler
import requests
import json
from watchdog.events import FileSystemEvent

class TestConfluenceAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Use a simpler base URL without /wiki/api/v2 since it's added in the API methods
        os.environ['CONFLUENCE_URL'] = 'https://your-domain'
        os.environ['CONFLUENCE_USERNAME'] = 'your_username'
        os.environ['CONFLUENCE_API_TOKEN'] = 'your_token'
        os.environ['CONFLUENCE_SPACE_KEY'] = 'your_space_key'

    def setUp(self):
        self.api = ConfluenceAPI()
        # Mock get_space_id to avoid that dependency in all tests
        self.api.get_space_id = MagicMock(return_value='test-space-id')
        # Ensure the content directory exists
        if not self.api.local.content_dir.exists():
            self.api.local.content_dir.mkdir(parents=True)

    @patch('sync_to_confluence.requests.Session.get')
    def test_get_attachments(self, mock_get):
        # Mock the response with proper _links structure
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'results': [{
                'id': '123',
                'title': 'test_attachment',
                '_links': {
                    'download': '/download/attachments/12345/test_attachment'
                }
            }],
            'size': 1  # Add size to indicate total results
        }
        # Mock the headers without a next link since we only want one page
        mock_response.headers = {}
        mock_get.return_value = mock_response

        attachments = self.api.get_attachments(page_id="12345", media_type="image/png", limit=1)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['title'], 'test_attachment')

    @patch('sync_to_confluence.requests.Session.get')
    def test_get_attachment_metadata(self, mock_get):
        # Mock the response for each API call
        mock_responses = {
            '/wiki/api/v2/attachments/123': {
                'id': '123',
                'title': 'test_attachment'
            },
            '/wiki/api/v2/attachments/123/versions': {
                'results': []
            },
            '/wiki/api/v2/attachments/123/labels': {
                'results': []
            },
            '/wiki/api/v2/attachments/123/properties': {
                'results': []
            }
        }

        def mock_get_response(*args, **kwargs):
            # Find the matching URL in mock_responses
            url = args[0] if args else kwargs.get('url', '')
            for endpoint, response_data in mock_responses.items():
                if endpoint in url:
                    mock_response = MagicMock()
                    mock_response.ok = True
                    mock_response.json.return_value = response_data
                    return mock_response
            return MagicMock(ok=False)

        mock_get.side_effect = mock_get_response

        metadata = self.api.get_attachment_metadata(attachment_id="123")
        self.assertEqual(metadata['title'], 'test_attachment')

    @patch('sync_to_confluence.requests.Session.get')
    def test_download_attachment(self, mock_get):
        # Mock the response with proper content
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.content = b'Test content'
        mock_get.return_value = mock_response

        attachment = {
            'id': '123',
            'title': 'test_attachment',
            '_links': {
                'download': '/download/attachments/12345/test_attachment'
            }
        }

        content = self.api.download_attachment(page_id="12345", attachment=attachment)
        self.assertEqual(content, b'Test content')

    @patch('sync_to_confluence.requests.Session.get')
    def test_get_attachments_error(self, mock_get):
        # Mock an error response
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 404
        mock_response.text = "Not found"
        mock_response.headers = {}
        # Configure the mock to raise an exception
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error: Not Found for url: test_url",
            response=mock_response
        )
        mock_get.return_value = mock_response

        with self.assertRaises(ConfluenceAPIError):
            self.api.get_attachments(page_id="12345")

    @patch('sync_to_confluence.requests.get')
    def test_logging_on_error(self, mock_get):
        # Mock an error response
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 500

        with self.assertRaises(ConfluenceAPIError):
            self.api.get_attachments(page_id="12345")

    @patch('sync_to_confluence.requests.Session.get')
    def test_get_space_content(self, mock_get):
        # Mock the response for the get_space_content method
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'results': [
                {'id': '1', 'title': 'Page 1'},
                {'id': '2', 'title': 'Page 2'},
            ],
            'size': 2
        }
        mock_get.return_value = mock_response

        # Call the method
        content = self.api.get_space_content()

        # Assertions
        self.assertEqual(len(content['results']), 2)
        self.assertEqual(content['results'][0]['title'], 'Page 1')
        self.assertEqual(content['results'][1]['title'], 'Page 2')

    @patch('sync_to_confluence.requests.Session.get')
    def test_get_page_by_id(self, mock_get):
        # Mock the response for the get_page_by_id method
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'id': '123',
            'title': 'Test Page',
            'body': {'storage': {'value': '<p>Test content</p>'}},
        }
        mock_get.return_value = mock_response

        # Call the method
        page = self.api.get_page_by_id('123')

        # Assertions
        self.assertEqual(page['id'], '123')
        self.assertEqual(page['title'], 'Test Page')
        self.assertIn('<p>Test content</p>', page['body']['storage']['value'])

    @patch('sync_to_confluence.requests.Session.get')
    @patch('sync_to_confluence.requests.Session.put')
    def test_update_page_success(self, mock_put, mock_get):
        # Mock successful page retrieval
        mock_get_response = MagicMock()
        mock_get_response.ok = True
        mock_get_response.json.return_value = {
            'id': '12345',
            'version': {'number': 1},
            'title': 'Test Page'
        }
        mock_get.return_value = mock_get_response

        # Mock successful page update
        mock_put_response = MagicMock()
        mock_put_response.ok = True
        mock_put_response.json.return_value = {
            'id': '12345',
            'version': {'number': 2},
            'title': 'Updated Test Page'
        }
        mock_put.return_value = mock_put_response

        content = {
            'title': 'Updated Test Page',
            'body': {'storage': {'value': 'Updated content'}}
        }

        result = self.api.update_page(page_id='12345', content=content)
        self.assertEqual(result['version']['number'], 2)
        self.assertEqual(result['title'], 'Updated Test Page')

    @patch('sync_to_confluence.requests.Session.get')
    @patch('sync_to_confluence.requests.Session.put')
    def test_update_page_version_conflict(self, mock_put, mock_get):
        # Mock initial page retrieval
        mock_get_response = MagicMock()
        mock_get_response.ok = True
        mock_get_response.json.side_effect = [
            {'id': '12345', 'version': {'number': 1}},  # First call
            {'id': '12345', 'version': {'number': 2}},  # After conflict
        ]
        mock_get.return_value = mock_get_response

        # Mock version conflict then success
        conflict_response = MagicMock()
        conflict_response.ok = False
        conflict_response.status_code = 409
        conflict_response.text = "Version conflict"
        conflict_response.json.return_value = {"message": "Version conflict detected"}
        conflict_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "409 Conflict",
            response=conflict_response
        )

        success_response = MagicMock()
        success_response.ok = True
        success_response.json.return_value = {
            'id': '12345',
            'version': {'number': 3},
            'title': 'Updated Test Page'
        }

        mock_put.side_effect = [
            requests.exceptions.HTTPError("409 Conflict", response=conflict_response),  # First call fails
            success_response  # Second call succeeds
        ]

        content = {
            'title': 'Updated Test Page',
            'body': {'storage': {'value': 'Updated content'}}
        }

        result = self.api.update_page(page_id='12345', content=content)
        self.assertEqual(result['version']['number'], 3)
        self.assertEqual(mock_put.call_count, 2)  # Verify retry occurred

    @patch('sync_to_confluence.requests.Session.get')
    @patch('sync_to_confluence.requests.Session.put')
    def test_update_page_bad_request(self, mock_put, mock_get):
        # Mock successful page retrieval
        mock_get_response = MagicMock()
        mock_get_response.ok = True
        mock_get_response.json.return_value = {
            'id': '12345',
            'version': {'number': 1}
        }
        mock_get.return_value = mock_get_response

        # Mock bad request error
        error_response = MagicMock()
        error_response.ok = False
        error_response.status_code = 400
        error_response.text = "Bad request"
        error_response.json.return_value = {
            "message": "Invalid page content",
            "details": "Body content cannot be empty"
        }

        mock_put.side_effect = requests.exceptions.HTTPError(
            "400 Bad Request",
            response=error_response
        )

        content = {
            'title': 'Test Page',
            'body': {'storage': {'value': ''}}  # Empty content to trigger error
        }

        with self.assertRaises(ConfluenceAPIError) as context:
            self.api.update_page(page_id='12345', content=content)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Invalid page content", str(context.exception))

    @patch('sync_to_confluence.requests.Session.get')
    @patch('sync_to_confluence.requests.Session.put')
    def test_update_page_max_retries_exceeded(self, mock_put, mock_get):
        # Mock page retrieval
        mock_get_response = MagicMock()
        mock_get_response.ok = True
        mock_get_response.json.return_value = {
            'id': '12345',
            'version': {'number': 1}
        }
        mock_get.return_value = mock_get_response

        # Mock persistent version conflict
        conflict_response = MagicMock()
        conflict_response.ok = False
        conflict_response.status_code = 409
        conflict_response.text = "Version conflict"
        conflict_response.json.return_value = {"message": "Version conflict detected"}

        # Configure mock to always raise conflict error
        mock_put.side_effect = [
            requests.exceptions.HTTPError("409 Conflict", response=conflict_response),
            requests.exceptions.HTTPError("409 Conflict", response=conflict_response),
            requests.exceptions.HTTPError("409 Conflict", response=conflict_response)
        ]

        content = {
            'title': 'Test Page',
            'body': {'storage': {'value': 'Test content'}}
        }

        with self.assertRaises(ConfluenceAPIError) as context:
            self.api.update_page(page_id='12345', content=content)

        self.assertEqual(mock_put.call_count, 3)  # Verify all retries were attempted
        self.assertEqual(context.exception.status_code, 409)

    @patch('sync_to_confluence.requests.Session.get')
    @patch('sync_to_confluence.requests.Session.put')
    def test_update_page(self, mock_put, mock_get):
        # Mock the response for the get_page_by_id method
        mock_response_get = MagicMock()
        mock_response_get.ok = True
        mock_response_get.json.return_value = {
            'id': '123',
            'title': 'Existing Page',
            'body': {'storage': {'value': '<p>Existing content</p>'}},
            'version': {'number': 1}
        }
        mock_get.return_value = mock_response_get

        # Mock the response for the update_page method
        mock_response_put = MagicMock()
        mock_response_put.ok = True
        mock_response_put.json.return_value = {
            'id': '123',
            'title': 'Updated Page',
            'version': {'number': 2}
        }
        mock_put.return_value = mock_response_put

        # Prepare the content to update
        content = {
            'title': 'Updated Page',
            'body': {'storage': {'value': '<p>Updated content</p>'}},
            'version': {'number': 2}
        }

        # Call the method
        updated_page = self.api.update_page('123', content)

        # Assertions
        self.assertEqual(updated_page['id'], '123')
        self.assertEqual(updated_page['title'], 'Updated Page')
        self.assertEqual(updated_page['version']['number'], 2)

    @patch('sync_to_confluence.requests.Session.post')
    def test_create_page(self, mock_post):
        # Mock the response for the create_page method
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'id': '123',
            'title': 'New Page',
            'version': {'number': 1}
        }
        mock_post.return_value = mock_response

        # Prepare the content to create
        content = {
            'title': 'New Page',
            'body': {'storage': {'value': '<p>New content</p>'}},
            'version': {'number': 1}
        }

        # Call the method
        created_page = self.api.create_page(content)

        # Assertions
        self.assertEqual(created_page['id'], '123')
        self.assertEqual(created_page['title'], 'New Page')
        self.assertEqual(created_page['version']['number'], 1)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_load_id_mapping(self, mock_open, mock_exists):
        # Setup mock data
        mock_data = '{"123": "new-page"}'
        mock_open.return_value.read.return_value = mock_data
        mock_exists.return_value = True

        # Create an instance of LocalContentManager
        local_manager = LocalContentManager()

        # Reset the mock to clear the initialization call
        mock_open.reset_mock()
        
        # Call the method to load the ID mapping
        mapping = local_manager._load_id_mapping()

        # Assertions
        expected_mapping = {"123": "new-page"}
        self.assertEqual(mapping, expected_mapping)

        # Verify that the file was opened correctly
        mock_open.assert_called_once_with('r')

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.unlink')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_delete_local_content(self, mock_open, mock_unlink, mock_exists):
        # Setup mocks
        mock_exists.return_value = True
        mock_data = '{"123": "new-page"}'
        mock_open.return_value.read.return_value = mock_data

        # Create an instance of LocalContentManager
        local_manager = LocalContentManager()

        # Reset mock to clear initialization calls
        mock_open.reset_mock()
        mock_exists.reset_mock()

        # Setup the ID mapping
        local_manager.id_to_filename = {"123": "new-page"}

        # Call the delete method
        filename = "new-page"
        local_manager.delete_local_content(filename)

        # Verify the file operations
        mock_exists.assert_called_with()
        mock_unlink.assert_called_once()
        
        # Verify that the ID mapping has been updated
        self.assertNotIn("123", local_manager.id_to_filename)

    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_save_content(self, mock_open):
        # Prepare the content to save
        page_id = '123'
        content = {
            'title': 'New Page',
            'body': {'storage': {'value': '<p>New content</p>'}},
        }

        # Create an instance of LocalContentManager
        local_manager = LocalContentManager()

        # Call the method
        local_manager.save_content(page_id, content)

        # Verify all file operations
        # First call should be to read the ID mapping
        self.assertEqual(mock_open.call_args_list[0], unittest.mock.call('r'))
        
        # Second call should be to save the ID mapping
        self.assertEqual(mock_open.call_args_list[1], unittest.mock.call('w'))
        
        # Third call should be to save the content
        self.assertEqual(mock_open.call_args_list[2], unittest.mock.call('w'))
        
        # Verify the content written
        write_calls = mock_open().write.call_args_list
        written_content = ''.join(call[0][0] for call in write_calls)
        self.assertIn('New Page', written_content)
        self.assertIn('<p>New content</p>', written_content)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_pull_from_confluence(self, mock_open, mock_exists):
        # Setup mock data
        space_content = {
            'results': [
                {'id': '123', 'title': 'Page 1'},
                {'id': '456', 'title': 'Page 2'},
            ]
        }
        
        full_page_1 = {
            'id': '123',
            'title': 'Page 1',
            'body': {'storage': {'value': '<p>Content 1</p>'}}
        }
        
        full_page_2 = {
            'id': '456',
            'title': 'Page 2',
            'body': {'storage': {'value': '<p>Content 2</p>'}}
        }
        
        attachments_1 = [
            {'id': 'att1', 'title': 'attachment1.pdf'},
            {'id': 'att2', 'title': 'attachment2.jpg'}
        ]
        
        # Setup mocks for file operations
        mock_exists.return_value = True
        mock_open.return_value.read.return_value = '{}'  # Empty JSON for deleted pages
        
        # Create mock dependencies
        confluence_api = MagicMock()
        confluence_api.get_space_content.return_value = space_content
        confluence_api.get_page_by_id.side_effect = lambda id: full_page_1 if id == '123' else full_page_2
        confluence_api.get_attachments.side_effect = lambda id: attachments_1 if id == '123' else []
        
        local_manager = MagicMock()
        
        # Create syncer and inject mocked dependencies
        syncer = ContentSyncer()
        syncer.confluence = confluence_api
        syncer.local = local_manager
        
        # Execute the pull operation
        syncer.pull_from_confluence()
        
        # Verify space content was retrieved
        confluence_api.get_space_content.assert_called_once()
        
        # Verify each page was processed
        confluence_api.get_page_by_id.assert_has_calls([
            call('123'),
            call('456')
        ])
        
        # Verify content was saved locally
        local_manager.save_content.assert_has_calls([
            call('123', full_page_1),
            call('456', full_page_2)
        ])
        
        # Verify attachments were retrieved
        confluence_api.get_attachments.assert_has_calls([
            call('123'),
            call('456')
        ])
        
        # Verify attachments were downloaded for page 1
        confluence_api._download_attachment.assert_has_calls([
            call('123', {'id': 'att1', 'title': 'attachment1.pdf'}),
            call('123', {'id': 'att2', 'title': 'attachment2.jpg'})
        ])

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_pull_from_confluence_with_errors(self, mock_open, mock_exists):
        # Setup mock data with errors
        space_content = {
            'results': [
                {'id': '123', 'title': 'Page 1'},
                {'id': '456', 'title': 'Page 2'},
            ]
        }
        
        # Setup mocks for file operations
        mock_exists.return_value = True
        mock_open.return_value.read.return_value = '{"789": true}'  # Deleted page
        
        # Create mock dependencies
        confluence_api = MagicMock()
        confluence_api.get_space_content.return_value = space_content
        
        # Simulate errors
        def get_page_by_id(id):
            if id == '123':
                return {'id': '123', 'title': 'Page 1'}
            raise ConfluenceAPIError('Page not found', status_code=404)
            
        confluence_api.get_page_by_id.side_effect = get_page_by_id
        confluence_api.get_attachments.side_effect = ConfluenceAPIError('Failed to get attachments', status_code=500)
        
        local_manager = MagicMock()
        
        # Create syncer and inject mocked dependencies
        syncer = ContentSyncer()
        syncer.confluence = confluence_api
        syncer.local = local_manager
        
        # Execute the pull operation
        syncer.pull_from_confluence()
        
        # Verify space content was retrieved
        confluence_api.get_space_content.assert_called_once()
        
        # Verify successful page was saved
        local_manager.save_content.assert_called_once_with('123', {'id': '123', 'title': 'Page 1'})
        
        # Verify error handling for attachments
        confluence_api.get_attachments.assert_called_once_with('123')
        confluence_api._download_attachment.assert_not_called()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_push_to_confluence(self, mock_open, mock_exists):
        # Setup mock data
        local_content = {
            'page1.json': {
                'hash': 'hash123',
                'content': {'id': '123', 'title': 'Page 1', 'body': {'storage': {'value': '<p>Content 1</p>'}}}
            },
            'page2.json': {
                'hash': 'hash456',
                'content': {'title': 'Page 2', 'body': {'storage': {'value': '<p>Content 2</p>'}}}
            }
        }
        
        # Setup cache data
        cache_data = {'page1.json': 'oldhash123'}
        
        # Mock file operations
        mock_exists.return_value = True
        
        # Setup file read mocks
        read_mock = MagicMock()
        
        def read_side_effect():
            filepath = str(mock_open.call_args[0][0])
            if filepath.endswith('.cache.json'):
                return json.dumps(cache_data)
            elif filepath.endswith('deleted_pages.json'):
                return '[]'
            return '{}'
            
        read_mock.side_effect = read_side_effect
        mock_open.return_value.read = read_mock
        
        # Create mock dependencies
        confluence_api = MagicMock()
        confluence_api.update_page.return_value = None
        confluence_api.create_page.return_value = {'id': 'new456'}
        
        local_manager = MagicMock()
        local_manager.get_local_content.return_value = local_content
        local_manager.get_page_id_from_filename.side_effect = lambda filename: local_content[filename]['content'].get('id')
        
        # Create syncer and inject mocked dependencies
        syncer = ContentSyncer()
        syncer.confluence = confluence_api
        syncer.local = local_manager
        
        # Execute the push operation
        syncer.push_to_confluence()
        
        # Verify local content was retrieved
        local_manager.get_local_content.assert_called_once()
        
        # Verify page updates and creations
        confluence_api.update_page.assert_called_once_with('123', local_content['page1.json']['content'])
        confluence_api.create_page.assert_called_once_with(local_content['page2.json']['content'])
        
        # Verify content was saved after creation
        local_manager.save_content.assert_called_once_with('new456', {'id': 'new456', 'title': 'Page 2', 'body': {'storage': {'value': '<p>Content 2</p>'}}})

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.open', new_callable=unittest.mock.mock_open)
    def test_push_to_confluence_with_errors(self, mock_open, mock_exists):
        # Setup mock data with errors
        local_content = {
            'page1.json': {
                'hash': 'hash123',
                'content': {'title': 'Page 1', 'body': {'storage': {'value': '<p>Content 1</p>'}}}
            }
        }
        
        # Mock file operations
        mock_exists.return_value = True
        
        # Setup file read mocks
        read_mock = MagicMock()
        
        def read_side_effect():
            filepath = str(mock_open.call_args[0][0])
            if filepath.endswith('.cache.json'):
                return '{}'
            elif filepath.endswith('deleted_pages.json'):
                return '[]'
            return '{}'
            
        read_mock.side_effect = read_side_effect
        mock_open.return_value.read = read_mock
        
        # Create mock dependencies
        confluence_api = MagicMock()
        confluence_api.create_page.side_effect = ConfluenceAPIError('Failed to create page', status_code=500)
        
        local_manager = MagicMock()
        local_manager.get_local_content.return_value = local_content
        local_manager.get_page_id_from_filename.return_value = None  # No existing page ID
        
        # Create syncer and inject mocked dependencies
        syncer = ContentSyncer()
        syncer.confluence = confluence_api
        syncer.local = local_manager
        
        # Execute the push operation
        syncer.push_to_confluence()
        
        # Verify local content was retrieved
        local_manager.get_local_content.assert_called_once()
        
        # Verify error handling for page creation
        confluence_api.create_page.assert_called_once_with(local_content['page1.json']['content'])
        confluence_api.update_page.assert_not_called()
        local_manager.save_content.assert_not_called()

class TestContentChangeHandler(unittest.TestCase):
    @patch('sync_to_confluence.ContentSyncer')
    def test_on_modified(self, MockContentSyncer):
        # Setup mock syncer
        mock_syncer = MockContentSyncer.return_value
        handler = ContentChangeHandler(mock_syncer)
        
        # Create a mock event for a modified JSON file
        mock_event = MagicMock(spec=FileSystemEvent)
        mock_event.is_directory = False
        mock_event.src_path = '/path/to/modified_file.json'
        
        # Call the on_modified method
        handler.on_modified(mock_event)
        
        # Verify that push_to_confluence was called
        mock_syncer.push_to_confluence.assert_called_once()
        
        # Verify logging
        with self.assertLogs('sync_to_confluence', level='INFO') as log:
            handler.on_modified(mock_event)
            self.assertIn("INFO:sync_to_confluence:Change detected in /path/to/modified_file.json", log.output)

    @patch('sync_to_confluence.ContentSyncer')
    def test_on_modified_non_json(self, MockContentSyncer):
        # Setup mock syncer
        mock_syncer = MockContentSyncer.return_value
        handler = ContentChangeHandler(mock_syncer)
        
        # Create a mock event for a modified non-JSON file
        mock_event = MagicMock(spec=FileSystemEvent)
        mock_event.is_directory = False
        mock_event.src_path = '/path/to/modified_file.txt'
        
        # Call the on_modified method
        handler.on_modified(mock_event)
        
        # Verify that push_to_confluence was not called
        mock_syncer.push_to_confluence.assert_not_called()

    @patch('sync_to_confluence.ContentSyncer')
    def test_on_modified_directory(self, MockContentSyncer):
        # Setup mock syncer
        mock_syncer = MockContentSyncer.return_value
        handler = ContentChangeHandler(mock_syncer)
        
        # Create a mock event for a directory modification
        mock_event = MagicMock(spec=FileSystemEvent)
        mock_event.is_directory = True
        mock_event.src_path = '/path/to/directory'
        
        # Call the on_modified method
        handler.on_modified(mock_event)
        
        # Verify that push_to_confluence was not called
        mock_syncer.push_to_confluence.assert_not_called()

    @patch('sync_to_confluence.ContentSyncer')
    def test_push_to_confluence_network_error(self, MockContentSyncer):
        # Setup mock syncer
        mock_syncer = MockContentSyncer.return_value
        handler = ContentChangeHandler(mock_syncer)
        
        # Create a mock event for a modified JSON file
        mock_event = MagicMock(spec=FileSystemEvent)
        mock_event.is_directory = False
        mock_event.src_path = '/path/to/modified_file.json'
        
        # Simulate a network error when pushing to Confluence
        mock_syncer.push_to_confluence.side_effect = ConnectionError('Network error')
        
        # Call the on_modified method
        with self.assertRaises(ConnectionError):
            handler.on_modified(mock_event)
        
        # Verify that push_to_confluence was called
        mock_syncer.push_to_confluence.assert_called_once()

    @patch('sync_to_confluence.ContentSyncer')
    def test_push_to_confluence_invalid_response(self, MockContentSyncer):
        # Setup mock syncer
        mock_syncer = MockContentSyncer.return_value
        handler = ContentChangeHandler(mock_syncer)
        
        # Create a mock event for a modified JSON file
        mock_event = MagicMock(spec=FileSystemEvent)
        mock_event.is_directory = False
        mock_event.src_path = '/path/to/modified_file.json'
        
        # Simulate an invalid response when pushing to Confluence
        mock_syncer.push_to_confluence.side_effect = ConfluenceAPIError('Invalid response', status_code=400)
        
        # Call the on_modified method
        with self.assertRaises(ConfluenceAPIError):
            handler.on_modified(mock_event)
        
        # Verify that push_to_confluence was called
        mock_syncer.push_to_confluence.assert_called_once()

if __name__ == '__main__':
    unittest.main()
