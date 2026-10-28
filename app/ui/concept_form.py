"""Pure concept form conversion; source records whether the owner edited it."""
from app.schemas.concept import Concept, ConceptCandidate


def concept_from_form(values, original=None):
    cleaned = {key: (values.get(key) or '').strip() for key in ('name', 'mood', 'tone', 'theme')}
    if not any(cleaned[key] for key in ('name', 'mood', 'tone')):
        return None
    candidate = ConceptCandidate.model_validate(cleaned).model_dump()
    baseline = {key: original.get(key) for key in candidate} if original else None
    source = original.get('source', '추천') if baseline == candidate else '직접'
    return Concept(**candidate, source=source).model_dump()
