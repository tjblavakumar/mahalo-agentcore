/**
 * API client for communicating with the MAHALO thin API.
 *
 * The thin-API Lambda Function URL uses AuthType=AWS_IAM, so every request must
 * be SigV4-signed with AWS credentials. The browser holds none at rest; it
 * fetches short-lived credentials from a Cognito (unauthenticated) identity
 * pool at runtime and signs each request in-browser with aws4fetch.
 */

import { AwsClient } from "aws4fetch";
import { fromCognitoIdentityPool } from "@aws-sdk/credential-providers";

/** Minimal shape of the temporary credentials returned by the provider. */
interface AwsCredentialIdentity {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
  expiration?: Date;
}

// Default is the thin-API Lambda Function URL convention
// (https://<id>.lambda-url.<region>.on.aws). Injected at build time via
// NEXT_PUBLIC_API_URL (see .env.example); no live backend is hardcoded.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://<function-id>.lambda-url.us-east-1.on.aws";

const AWS_REGION = process.env.NEXT_PUBLIC_AWS_REGION || "us-east-1";
const IDENTITY_POOL_ID = process.env.NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID || "";

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
}

function normalizeErrorMessage(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeErrorMessage(item))
      .filter(Boolean)
      .join("; ");
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const candidate = record.msg ?? record.message ?? record.detail;
    if (candidate) {
      return normalizeErrorMessage(candidate);
    }

    try {
      return JSON.stringify(value);
    } catch {
      return "Request failed";
    }
  }

  return "Request failed";
}

// --- SigV4 auth: Cognito temp creds -> in-browser signer -------------------

// Temporary credentials live in memory only (never sessionStorage/localStorage).
let cachedCredentials: AwsCredentialIdentity | null = null;
let credentialProvider: ReturnType<typeof fromCognitoIdentityPool> | null = null;

// Refresh a little before the hard expiry so a request never signs with a
// credential that expires in flight.
const EXPIRY_SKEW_MS = 60_000;

function getProvider(): ReturnType<typeof fromCognitoIdentityPool> {
  if (!credentialProvider) {
    credentialProvider = fromCognitoIdentityPool({
      identityPoolId: IDENTITY_POOL_ID,
      clientConfig: { region: AWS_REGION },
    });
  }
  return credentialProvider;
}

function credentialsAreFresh(creds: AwsCredentialIdentity | null): boolean {
  if (!creds) return false;
  if (!creds.expiration) return true;
  return creds.expiration.getTime() - EXPIRY_SKEW_MS > Date.now();
}

async function getCredentials(): Promise<AwsCredentialIdentity> {
  if (credentialsAreFresh(cachedCredentials)) {
    return cachedCredentials!;
  }
  cachedCredentials = await getProvider()();
  return cachedCredentials;
}

async function getSigner(): Promise<AwsClient> {
  const creds = await getCredentials();
  return new AwsClient({
    accessKeyId: creds.accessKeyId,
    secretAccessKey: creds.secretAccessKey,
    sessionToken: creds.sessionToken,
    service: "lambda",
    region: AWS_REGION,
  });
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((options.headers as Record<string, string>) || {}),
    };

    let aws: AwsClient;
    try {
      aws = await getSigner();
    } catch (authErr) {
      console.error("Identity-pool credential fetch failed", authErr);
      return {
        data: null,
        error: "Could not authenticate to the API",
      };
    }

    // Pass the serialized body INTO aws.fetch so the signer computes
    // X-Amz-Content-Sha256 over the exact bytes sent. Do NOT mutate headers or
    // body after signing, or the edge recomputation will not match (403).
    const response = await aws.fetch(url, {
      method: options.method,
      headers,
      body: options.body,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMessage =
        normalizeErrorMessage(errorData.detail) ||
        normalizeErrorMessage(errorData.message) ||
        `Request failed with status ${response.status}`;

      return {
        data: null,
        error: errorMessage,
      };
    }

    const data = await response.json();
    return { data, error: null };
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : "An unknown error occurred",
    };
  }
}

export const api = {
  get: <T>(endpoint: string) => request<T>(endpoint, { method: "GET" }),
  post: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, { method: "PUT", body: JSON.stringify(body) }),
  delete: <T>(endpoint: string) => request<T>(endpoint, { method: "DELETE" }),
};

export type { ApiResponse };
export { API_BASE_URL };
