# GitHub Actions Workflows

**IMPORTANT: GitHub Actions workflows have been disabled for this repository.**

This project uses Railway's direct GitHub integration for deployments instead of GitHub Actions.

## Deployment Process

Deployments are automatically triggered when changes are pushed to the main branch through Railway's direct GitHub integration.

## Storage Configuration

This project uses MinIO for object storage with the following configuration:

- Primary storage: MinIO
- Configuration: Environment variables in Railway
- URL format: Handles both internal Railway endpoints and cross-project endpoints

For more details, see the `RAILWAY_MINIO_SETUP.md` file in the repository.
