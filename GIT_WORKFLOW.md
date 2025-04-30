# Git Workflow for NCA-toolkit-Thai-text

This document outlines the Git workflow for maintaining stable versions and deploying to Google Cloud.

## Branch Structure

- **stable-main**: Contains the stable, well-tested version of the code
- **main**: Deployment branch that triggers CI/CD pipeline to Google Cloud
- **feature/\***: Feature branches for new development work

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

### Regular Development Workflow

1. **Start a new feature**

   Always create a new branch for each feature or bug fix:

   ```cmd
   git checkout stable-main
   git pull origin stable-main
   git checkout -b feature/new-feature-name
   ```

2. **Work on your feature**

   Make changes, commit frequently with descriptive messages:

   ```cmd
   git add .
   git commit -m "Descriptive message about your changes"
   ```

3. **Update your feature branch with latest stable changes (if needed)**

   ```cmd
   git checkout stable-main
   git pull origin stable-main
   git checkout feature/new-feature-name
   git merge stable-main
   ```

4. **Update the stable branch when feature is complete and tested**

   ```cmd
   git checkout stable-main
   git merge feature/new-feature-name
   git push origin stable-main
   ```

5. **Deploy to Google Cloud**

   ```cmd
   git checkout main
   git merge feature/new-feature-name
   git push origin main  # This triggers deployment
   ```

## Handling Issues After Deployment

If you encounter problems after deployment:

1. **Revert the deployment branch to the stable version**

   ```cmd
   git checkout main
   git reset --hard stable-main
   git push --force origin main  # This will trigger a new deployment with the stable code
   ```

2. **Fix issues on a new feature branch**

   ```cmd
   git checkout stable-main
   git checkout -b fix/deployment-issue
   # Make fixes
   ```

3. **Follow the regular workflow** to update stable and then deploy

## Creating New Stable Versions

When you reach a new stable milestone:

```cmd
# Update the stable branch with your latest features
git checkout stable-main
git merge feature/your-latest-feature
git push origin stable-main

# Create a new version tag
git tag -a v1.1.0 -m "Description of this version's features"
git push origin v1.1.0
```

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

## Deployment Configuration

### Cloud Build Setup

- **Build Region**: Uses a global region (us-central1) for Cloud Build
- **Deployment Region**: Deploys to asia-southeast1 for Cloud Run
- **Logging**: Uses CLOUD_LOGGING_ONLY option for build logs
- **Trigger**: Configured to run on pushes to the main branch

### Checking Deployment Status

After pushing to the main branch, you can check the deployment status in the Google Cloud Console:

1. Go to Cloud Build > History
2. Look for the latest build triggered by your push
3. Check the logs for any errors

### Viewing Configuration Files in Windows

To check your deployment configuration:

```cmd
# View cloudbuild.yaml
type cloudbuild.yaml

# Or using more for pagination
more cloudbuild.yaml
```

## Recent Updates

- **v1.0.0** (May 1, 2025): Stable version with adaptive text splitting and adjustable padding
