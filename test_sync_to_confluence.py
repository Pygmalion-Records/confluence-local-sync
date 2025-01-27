import os
import unittest
from unittest.mock import patch, MagicMock
from sync_to_confluence import ConfluenceAPI, ConfluenceAPIError
import requests

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

if __name__ == '__main__':
    unittest.main()
