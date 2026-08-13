"""Figure image storage: URLs attached, temp paths stripped, failures survivable."""

import pytest

from services.figure_storage import FigureStorage, MAX_FIGURE_BYTES


class FakeBucket:
    """Records uploads and hands back predictable URLs."""

    def __init__(self, fail_on=None):
        self.uploaded = {}
        self._fail_on = fail_on or set()

    def upload(self, path, file, file_options):
        if path in self._fail_on:
            raise RuntimeError('storage rejected the upload')
        self.uploaded[path] = file

    def get_public_url(self, path):
        return f'https://cdn.test/figures/{path}'


class FakeSupabase:
    """Stands in for the Supabase client's storage API.

    `exists=False` models a fresh project, where no bucket has been created yet
    — the state that made every upload 404 and every figure arrive imageless.
    """

    def __init__(self, bucket, exists=True):
        self._bucket = bucket
        self._exists = exists
        self.created = []
        self.get_bucket_calls = 0
        self.storage = self

    def from_(self, _name):
        return self._bucket

    def get_bucket(self, name):
        self.get_bucket_calls += 1
        if not self._exists:
            raise RuntimeError('Bucket not found')
        return {'name': name}

    def create_bucket(self, name, options=None):
        self.created.append((name, options))
        self._exists = True


@pytest.fixture
def png(tmp_path):
    def _make(name='fig.png', data=b'\x89PNG\r\n\x1a\n' + b'x' * 100):
        p = tmp_path / name
        p.write_bytes(data)
        return p
    return _make


@pytest.mark.asyncio
async def test_uploads_image_and_attaches_url(png):
    bucket = FakeBucket()
    storage = FigureStorage(FakeSupabase(bucket))

    out = await storage.attach_urls('sum-1', [{'caption': 'Fig 1', 'path': str(png())}])

    assert out[0]['image_url'] == 'https://cdn.test/figures/sum-1/000.png'
    assert out[0]['caption'] == 'Fig 1'
    assert len(bucket.uploaded) == 1


@pytest.mark.asyncio
async def test_temp_path_never_survives_into_the_record(png):
    """`path` points into a temp dir that is deleted when the request ends."""
    storage = FigureStorage(FakeSupabase(FakeBucket()))
    out = await storage.attach_urls('sum-1', [{'caption': 'c', 'path': str(png())}])
    assert 'path' not in out[0]


@pytest.mark.asyncio
async def test_upload_failure_keeps_the_caption(png):
    """A figure without an image is still a figure; it must not sink the paper."""
    bucket = FakeBucket(fail_on={'sum-1/000.png'})
    storage = FigureStorage(FakeSupabase(bucket))

    out = await storage.attach_urls('sum-1', [{'caption': 'Fig 1', 'path': str(png())}])

    assert len(out) == 1
    assert out[0]['caption'] == 'Fig 1'
    assert 'image_url' not in out[0]
    assert 'path' not in out[0]


@pytest.mark.asyncio
async def test_missing_file_is_skipped_not_fatal():
    storage = FigureStorage(FakeSupabase(FakeBucket()))
    out = await storage.attach_urls('sum-1', [{'caption': 'c', 'path': '/no/such/file.png'}])
    assert out[0]['caption'] == 'c'
    assert 'image_url' not in out[0]


@pytest.mark.asyncio
async def test_oversized_figure_is_skipped(png):
    storage = FigureStorage(FakeSupabase(FakeBucket()))
    big = png('big.png', b'x' * (MAX_FIGURE_BYTES + 1))
    out = await storage.attach_urls('sum-1', [{'caption': 'c', 'path': str(big)}])
    assert 'image_url' not in out[0]


@pytest.mark.asyncio
async def test_figures_keep_their_order_and_count(png):
    storage = FigureStorage(FakeSupabase(FakeBucket()))
    figures = [{'caption': f'Fig {i}', 'path': str(png(f'f{i}.png'))} for i in range(4)]

    out = await storage.attach_urls('sum-1', figures)

    assert [f['caption'] for f in out] == ['Fig 0', 'Fig 1', 'Fig 2', 'Fig 3']
    assert out[2]['image_url'].endswith('002.png')


@pytest.mark.asyncio
async def test_empty_input_short_circuits():
    storage = FigureStorage(FakeSupabase(FakeBucket()))
    assert await storage.attach_urls('sum-1', []) == []


@pytest.mark.asyncio
async def test_missing_bucket_is_created_before_uploading(png):
    """A project with no `figures` bucket must provision one, not lose the image."""
    supabase = FakeSupabase(FakeBucket(), exists=False)
    storage = FigureStorage(supabase)

    out = await storage.attach_urls('sum-1', [{'caption': 'c', 'path': str(png())}])

    assert supabase.created and supabase.created[0][0] == 'figures'
    # Browsers load these straight from an <img>, with no session to sign with.
    assert supabase.created[0][1]['public'] is True
    assert out[0]['image_url'].endswith('sum-1/000.png')


@pytest.mark.asyncio
async def test_existing_bucket_is_not_recreated(png):
    supabase = FakeSupabase(FakeBucket())
    storage = FigureStorage(supabase)

    await storage.attach_urls('sum-1', [{'caption': 'c', 'path': str(png())}])
    await storage.attach_urls('sum-2', [{'caption': 'c', 'path': str(png())}])

    assert supabase.created == []
    # The probe is per-instance, not per-paper.
    assert supabase.get_bucket_calls == 1
