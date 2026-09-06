# Spark Dodge

Single-page canvas game. No build step or dependencies — `index.html` is the whole app.

Run locally:

```bash
python3 -m http.server 8000 --directory games/spark-dodge
```

## Deployment

Hosted as a static site on a private S3 bucket fronted by CloudFront (origin access control, HTTPS only) in `us-east-1`.

Publish an update:

```bash
aws s3 cp games/spark-dodge/index.html "s3://$BUCKET/index.html" --content-type text/html --profile "$AWS_PROFILE"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths '/*' --profile "$AWS_PROFILE"
```
