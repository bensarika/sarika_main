# Sarika Pong

Single-page canvas game. No build step or dependencies — `index.html` is the whole app.

Sarika-branded: maroon/cream palette and the six-petal mark from sarika.com (inlined as SVG),
bispecific antibodies drawn as canvas paths with a different color per arm, and an FcRn receptor
catcher anchored through a phospholipid bilayer on two transmembrane poles.

Scoring is the number of antibodies caught. Some antibodies fall with a red antigen bound in their
Fab cleft; catching one of those exposes it and ends the run. The share of antigen-bound spawns
ramps from 10% up to 75% the longer a run lasts, which is the difficulty curve.

The SARIKA LEADERBOARD panel (beside the canvas, below it on narrow screens) is company-wide and
lives in S3. Browsers can't write to S3 safely, so `leaderboard/lambda_function.py` runs behind a
public Lambda Function URL and owns the object: `GET` returns the top scores, `POST {name, score}`
merges one in under an ETag-conditional write. Names are sanitized and capped at 16 characters,
scores are bounded, and the list is trimmed to 20 entries. Submissions are unauthenticated, so
scores are trust-based.

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

Update the leaderboard function (same bucket holds `leaderboard.json`):

```bash
cd games/spark-dodge/leaderboard && zip -q /tmp/lb.zip lambda_function.py
aws lambda update-function-code --function-name sarika-pong-leaderboard --zip-file fileb:///tmp/lb.zip --profile "$AWS_PROFILE"
```
