// Reuse the existing Express API as a Netlify Function. The Python ML service
// remains a separate HTTP service; the Express allowlist proxies to ML_SERVICE_URL.
process.env.NODE_ENV ??= 'production';

import app from '../../backend/src/app.js';
import serverless from 'serverless-http';

export const handler = serverless(app);