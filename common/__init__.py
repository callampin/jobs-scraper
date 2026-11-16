"""Utilidades compartidas por los conectores de ofertas de empleo."""

JOB_FIELDS = (
    "source",
    "job_id",
    "title",
    "company",
    "location",
    "modality",
    "salary",
    "published_at",
    "url",
    "description",
    "tags",
    "scraped_at",
)

__all__ = ["JOB_FIELDS"]
