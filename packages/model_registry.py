"""Register all SQL models before schema inspection or isolated test DDL."""

from packages.documents.models import Document  # noqa: F401
from packages.identity.models import User  # noqa: F401
from packages.indexing.models import IndexRevision  # noqa: F401
from packages.parsers.models import Extraction  # noqa: F401
from packages.processing.models import ProcessingJob  # noqa: F401
from packages.rag.models import GenerationRun  # noqa: F401
