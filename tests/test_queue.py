import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
import queue_api


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'QUEUE_API_TOKEN': 'test-secret',
            'QUEUE_DB_PATH': self.temp.name + '/jobs.sqlite3',
        })
        self.env.start()
        self.client = TestClient(queue_api.app)
        self.headers = {'Authorization': 'Bearer test-secret'}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.headers)

    def submit(self):
        response = self.post('/jobs', {'url': 'https://app.joinhandshake.com/job-search/123'})
        self.assertEqual(response.status_code, 202)
        return response.json()['id']

    def test_auth_and_host_validation(self):
        self.assertEqual(self.client.post('/worker/claim').status_code, 401)
        self.assertEqual(self.client.get('/jobs/anything').status_code, 401)
        for url in ['http://localhost', 'https://joinhandshake.com.evil.test/', 'https://user:password@app.joinhandshake.com/']:
            self.assertEqual(self.post('/jobs', {'url': url}).status_code, 422)
        with patch.dict(os.environ, {'QUEUE_API_TOKEN': ''}):
            self.assertEqual(self.post('/worker/claim', {}).status_code, 503)

    def test_result_delivery_and_retry(self):
        job_id = self.submit()
        job = self.post('/worker/claim', {}).json()['job']
        self.assertEqual(job['id'], job_id)
        self.assertIsNone(self.post('/worker/claim', {}).json()['job'])
        self.assertEqual(self.post(f'/worker/{job_id}/heartbeat', {'claim_token': job['claim_token']}).status_code, 200)
        body = {'claim_token': job['claim_token'], 'result': {'job_description': 'Example'}}
        for _ in range(2):
            self.assertEqual(self.post(f'/worker/{job_id}/complete', body).status_code, 200)
        result = self.client.get(f'/jobs/{job_id}', headers=self.headers).json()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result'], body['result'])
        self.assertNotIn('claim_token', result)

    def test_expired_claim_recovery(self):
        job_id = self.submit()
        old = self.post('/worker/claim', {}).json()['job']
        with queue_api.database() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (job_id,))
        new = self.post('/worker/claim', {}).json()['job']
        self.assertNotEqual(old['claim_token'], new['claim_token'])
        self.assertEqual(self.post(f'/worker/{job_id}/complete', {'claim_token': old['claim_token']}).status_code, 409)
        self.assertEqual(self.post(f'/worker/{job_id}/complete', {'claim_token': new['claim_token'], 'error': 'Login expired'}).status_code, 200)
        self.assertEqual(self.client.get(f'/jobs/{job_id}', headers=self.headers).json()['status'], 'failed')

    def test_atomic_claim(self):
        self.submit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: queue_api.claim(), range(2)))
        self.assertEqual(sum(reply['job'] is not None for reply in replies), 1)


if __name__ == '__main__':
    unittest.main()
