export interface InboxItem {
  mailbox_email_id: number;
  email_id: string;
  subject: string | null;
  from_addr: string | null;
  received_at: string | null;
  category?: string | null;
  auto_category?: string | null;
  manual_category?: string | null;
  has_summary?: boolean;
  last_action_status?: string | null;
  last_action_at?: string | null;
  has_draft_reply?: boolean;
  has_translation?: boolean;
  has_extraction?: boolean;
}

export interface InboxResponse {
  status: string;
  mailbox_id: string;
  items: InboxItem[];
}

export interface EmailDetail {
  email_id: string;
  subject: string | null;
  from_addr: string | null;
  to_addrs: string | null;
  cc_addrs: string | null;
  received_at: string | null;
  body_text: string | null;
  body_html: string | null;
  category: string | null;
  urgency: string | null;
  updated_ts: string | null;
  classification_history: Array<{
    category: string;
    rule_name: string | null;
    confidence: number | null;
    created_ts: string | null;
  }>;
}

export interface Artifact {
  artifact_id: string;
  artifact_type: string;
  content_text?: string | null;
  content_json?: string | Record<string, unknown> | null;
  language?: string | null;
  created_at?: string | null;
  run_id?: string;
  run_status?: string;
  params_json?: string | null;
}

export interface ArtifactsResponse {
  status: string;
  mailbox_id: string;
  email_id: string;
  items: Artifact[];
}

export interface DatasetSummary {
  status: string;
  totals: { raw_messages: number; canonical_emails: number; mailbox_mappings: number };
  mailbox_totals: Array<{ mailbox_id: string; count: number }>;
  date_coverage: Record<string, { min: string | null; max: string | null }>;
  category_distribution?: Record<string, Array<{ category: string; count: number }>>;
  action_coverage?: Array<{ action_type: string; count: number }>;
  artifact_coverage?: Array<{ artifact_type: string; count: number }>;
}

export interface ExecutionRun {
  run_id: string;
  mailbox_id: string;
  email_id: string;
  action_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  model_name: string | null;
  error_message: string | null;
  subject: string | null;
}

export interface AuditRunsResponse {
  status: string;
  items: ExecutionRun[];
  total_runs: number;
  success_count: number;
  failed_count: number;
}

export interface TaxonomyItem {
  classification_id: string;
  name: string;
  description: string;
}

export interface ClassificationMetrics {
  status: string;
  labeled_count: number;
  macro: { precision: number; recall: number; f1: number };
  per_class: Record<string, { precision: number; recall: number; f1: number }>;
  confusion_matrix: Array<{ actual: string; predicted: string; count: number }>;
}

export interface TaxonomyDiscoverResponse {
  status: string;
  sampled_count: number;
  proposed_taxonomy: TaxonomyItem[];
}
