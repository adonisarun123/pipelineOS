export interface Auth {
  token: string;
  user_id: number;
  username: string;
  role: "admin" | "manager" | "member" | "readonly";
}

export interface Stage {
  id: number;
  name: string;
  order: number;
  rot_days: number | null;
  probability: number | null;
}

export interface Pipeline {
  id: number;
  name: string;
  order: number;
  stages: Stage[];
}

export interface Deal {
  id: number;
  title: string;
  value: string;
  currency: string;
  pipeline: number;
  stage: number;
  owner: number;
  owner_name: string;
  organization: number | null;
  organization_name: string | null;
  status: "open" | "won" | "lost";
  is_rotten: boolean;
  needs_next_activity: boolean;
  custom: Record<string, unknown>;
}

export interface CustomFieldDef {
  id: number;
  entity: string;
  name: string;
  key: string;
  field_type: string;
  options: string[];
  is_important: boolean;
  pipeline: number | null;
  order: number;
}

export interface KanbanColumn {
  stage: { id: number; name: string; rot_days: number | null; probability: number | null };
  count: number;
  total_value: string;
  deals: Deal[];
}

export interface Kanban {
  pipeline: { id: number; name: string };
  columns: KanbanColumn[];
}

export type LeadStatus = "new" | "attempted" | "contacted" | "qualified" | "disqualified";

export interface Lead {
  id: number;
  name: string;
  organization_name: string;
  phone_raw: string;
  phone_normalized: string;
  email: string;
  source: number | null;
  source_name: string | null;
  owner: number | null;
  owner_name: string | null;
  status: LeadStatus;
  note: string;
  converted_deal: number | null;
  created_at: string;
}

export interface LostReason {
  id: number;
  label: string;
}

export interface LeadSource {
  id: number;
  name: string;
}

export interface Paginated<T> {
  results: T[];
  next: string | null;
  previous: string | null;
}
