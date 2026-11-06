// Reuse the existing Express API as a Netlify Function. The Python ML service
// remains a separate HTTP service; the Express allowlist proxies to ML_SERVICE_URL.
process.env.NODE_ENV ??= 'production';

const [{ default: app }, { default: serverless }] = await Promise.all([
  import('../../backend/src/app.js'),
  import('serverless-http'),
]);

export const handler = serverless(app);
