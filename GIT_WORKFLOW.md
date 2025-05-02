# Git Workflow for NCA-toolkit-Thai-text

This document outlines the Git workflow for maintaining stable versions and deploying to Railway.

## Branch Structure

- **stable-main**: Contains the stable, well-tested version of the code
- **main**: Deployment branch that triggers CI/CD pipeline to Railway
- **feature/\***: Feature branches for new development work
- **deploy/\***: Temporary deployment branches for testing specific features

## Workflow for Development

### Initial Setup (Completed)

```cmd
# Create the stable branch from current state
git branch stable-main
git push origin stable-main

# Tag the stable version
git tag -a v1.0.0 -m "Stable version with adaptive text splitting and adjustable padding"
git push origin v1.0.0
```

### Feature Development

1. Create a feature branch from stable-main:
```cmd
git checkout stable-main
git pull origin stable-main
git checkout -b feature/new-feature-name
```

2. Make changes and commit them:
```cmd
git add .
git commit -m "Descriptive message about your changes"
```

3. Push the feature branch to GitHub:
```cmd
git push origin feature/new-feature-name
```

### Testing Deployment

To test a feature before merging to main:

1. Create a deployment branch from your feature branch:
```cmd
git checkout feature/new-feature-name
git checkout -b deploy/new-feature-name
git push origin deploy/new-feature-name
```

2. Railway will automatically deploy this branch to a preview environment (if configured).

### Production Deployment

When ready to deploy to production:

1. Merge your feature branch to main:
```cmd
git checkout main
git pull origin main
git merge feature/new-feature-name
git push origin main
```

2. Railway will automatically deploy the main branch to production.

### Updating Stable Version

After confirming the deployment works correctly:

1. Update the stable branch:
```cmd
git checkout stable-main
git pull origin stable-main
git merge main
git push origin stable-main

# Create a new version tag
git tag -a v1.1.0 -m "Description of this version's features"
git push origin v1.1.0
```

## Reverting to Stable Version

If a deployment causes issues:

1. Force reset main to stable-main:
```cmd
git checkout main
git reset --hard stable-main
git push --force origin main
```

2. This will trigger a new deployment with the stable version.

## Railway-Specific Configuration

Railway uses the following for deployment:
- The `main` branch is automatically deployed to production
- Other branches can be deployed to preview environments
- Railway uses the Dockerfile at the root of the project for builds
- Environment variables are configured in the Railway dashboard
- The service is accessible at: nca-toolkit-thai-text-github.railway.internal

## Best Practices

1. **Never commit directly to main or stable-main** - always use feature branches
2. **Test thoroughly before updating stable-main**
3. **Use descriptive commit messages**
4. **Create meaningful tags** for important versions
5. **Consider using semantic versioning** for your tags:
   - X.Y.Z format
   - X: Major version (breaking changes)
   - Y: Minor version (new features, non-breaking)
   - Z: Patch version (bug fixes)

## Recent Updates

- **v1.0.0** (May 1, 2025): Stable version with adaptive text splitting and adjustable padding
