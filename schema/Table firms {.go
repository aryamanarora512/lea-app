Table firms {
  firm_id text [pk]
  firm_name text
  state text
  city text
  acquisition_date date
  primary_practice text
  cms_platform text
  total_headcount int
  notes text
}
 
Table categories {
  category_id text [pk]
  category_name text
  description text
  sort_order int
}
 
Table fin_case_unit_economics {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  total_cases_settled int
  total_gross_settlement real
  total_net_fee real
  total_case_costs_advanced real
  avg_gross_settlement real
  avg_net_fee real
  avg_case_costs real
  avg_fee_pct real
  avg_case_duration_days int
  settlements_per_attorney real
  revenue_per_attorney real
  cost_to_revenue_ratio real
}
 
Table fin_pnl_breakdown {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  gross_revenue real
  net_revenue real
  attorney_salaries real
  staff_salaries real
  marketing_spend real
  case_costs_advanced real
  office_rent real
  technology_costs real
  insurance real
  other_costs real
  total_operating_costs real
  ebitda real
  ebitda_margin real
  net_income real
  net_margin real
}
 
Table fin_practice_area_profitability {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  practice_area text
  case_count int
  gross_revenue real
  net_revenue real
  total_costs real
  profit real
  profit_margin real
  avg_case_value real
  avg_net_fee real
  avg_duration_days int
  cases_per_attorney real
}
 
Table cas_top_25_cases {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  snapshot_date date
  rank int
  practice_area text
  injury_type text
  county text
  supervising_attorney text
  gross_settlement real
  net_fee real
  case_costs_advanced real
  case_duration_days int
  insurance_carrier text
}
 
Table cas_cases_opened_over_time {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  practice_area text
  acquisition_method text
  cases_opened int
  estimated_pipeline_value real
}
 
Table cas_closed_cases {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  quarter int
  case_type text
  cases_count int
  fee_income real
  avg_fee_per_case real
}
 
Table cas_current_inventory {
  case_id text [pk]
  firm_id text [ref: > firms.firm_id]
  snapshot_date date
  practice_area text
  injury_type text
  acquisition_method text
  county text
  state text
  current_stage text
  supervising_attorney text
  case_costs_advanced real
  estimated_value real
  age_days int
  insurance_carrier text
  policy_limit real
}
 
Table cas_inventory_aging {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  snapshot_date date
  practice_area text
  age_bucket text
  case_count int
  total_costs_advanced real
  avg_costs_per_case real
  total_estimated_value real
}
 
Table cas_costs_over_time {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  practice_area text
  total_costs_advanced real
  cumulative_outstanding real
  avg_cost_per_case real
  cases_with_costs_count int
}
 
Table cas_win_trial_rate {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  practice_area text
  total_cases_closed int
  cases_to_trial int
  trials_won int
  trials_lost int
  settled_without_trial int
  trial_rate real
  win_rate_at_trial real
  avg_settlement_pretrial real
  avg_settlement_attrial real
}
 

Table lit_profitability {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  track text
  case_count int
  avg_gross_settlement real
  avg_net_fee real
  avg_fee_pct real
  avg_case_costs real
  avg_profit_per_case real
  total_revenue real
}
 
Table lit_volume_trends {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  track text
  cases_opened int
  cases_settled int
  cases_pending int
  pct_of_total_inventory real
}
 
Table lit_case_timing {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  track text
  avg_duration_days int
  median_duration_days int
  p25_days int
  p75_days int
  avg_time_to_demand_days int
  avg_time_to_settlement_days int
}
 
Table per_employee_census {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  employee_number int
  full_name text
  dept_title text
  function_role text
  division text
  employment_status text
  start_date date
  comp_method text
  annual_salary real
  annual_bonus real
  total_annual_comp real
  notes text
  is_active int
}
 
Table per_employee_productivity {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  employee_number int
  full_name text
  period_year int
  division text
  cases_managed int
  cases_settled int
  gross_revenue_generated real
  net_revenue_generated real
  avg_settlement_per_case real
  cost_to_employ real
}
 
Table per_key_person_risk {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  employee_number int
  employee_name text
  role text
  years_at_firm real
  revenue_attributed real
  pct_of_firm_revenue real
  has_non_compete int
  risk_level text
  risk_notes text
}
 
Table per_org_chart {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  employee_number int
  full_name text
  title text
  division text
  reports_to_employee_number int
  direct_report_count int
}
 
Table per_senior_junior_ratios {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  snapshot_date date
  division text
  total_attorneys int
  senior_attorney_count int
  junior_attorney_count int
  of_counsel_count int
  paralegal_count int
  case_manager_count int
  support_staff_count int
  admin_count int
  senior_to_junior_ratio real
  attorney_to_staff_ratio real
}
 

Table mkt_spend_mix {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  channel text
  vendor text
  spend real
  pct_of_total_budget real
}
 
Table mkt_lead_gen_source {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  lead_source text
  vendor text
  leads_generated int
  pct_of_total_leads real
  cases_signed int
  conversion_rate real
  revenue_attributed real
  concentration_risk_flag int
}
 
Table mkt_performance {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  channel text
  spend real
  leads_generated int
  cases_signed int
  revenue_attributed real
  cost_per_lead real
  cost_per_case real
  lead_to_sign_rate real
  roas real
}
 
Table int_funnel {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  period_month int
  practice_area text
  lead_source text
  leads_received int
  leads_contacted int
  leads_qualified int
  leads_signed int
  contact_rate real
  qualification_rate real
  sign_rate real
  overall_conversion_rate real
  avg_time_to_contact_hours real
  avg_time_to_sign_days real
}
 
Table int_workflow {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  step_order int
  step_name text
  responsible_role text
  tools_used text
  avg_duration_hours real
  is_automated int
  notes text
}
 
Table ref_outbound {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  receiving_firm_name text
  relationship_type text
  practice_area text
  cases_referred_out int
  total_referral_fees_paid real
  avg_case_value real
  reason_for_referral text
}
 
Table ref_inbound {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  source_name text
  source_type text
  practice_area text
  cases_received int
  total_revenue_from_source real
  avg_case_value real
  referral_fees_received real
  pct_of_total_new_cases real
  concentration_risk_flag int
}
 
Table geo_office_performance {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  office_name text
  city text
  state text
  period_year int
  new_matters_opened int
  cases_settled int
  pending_cases int
  gross_revenue real
  net_revenue real
  attorney_headcount int
  support_staff_headcount int
  revenue_per_attorney real
  cases_per_attorney real
}
 
Table geo_office_overview {
  office_id text [pk]
  firm_id text [ref: > firms.firm_id]
  office_name text
  city text
  state text
  county text
  address text
  square_footage int
  monthly_rent real
  lease_expiry date
  has_renewal_option int
  is_active int
}
 
Table geo_footprint {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  period_year int
  state text
  county text
  case_volume int
  gross_revenue real
  pct_of_firm_total real
  has_physical_office int
  overlap_with_other_lea_firm int
}
 
Table tec_tools {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  tool_name text
  category text
  vendor text
  monthly_cost real
  contract_expiry date
  auto_renews int
  primary_users text
  integration_status text
  satisfaction_score int
  notes text
}
 
Table com_competitor_reviews {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  entity_name text
  is_portfolio_firm int
  platform text
  avg_rating real
  review_count int
  positive_review_pct real
  negative_review_pct real
  common_praise_themes text
  common_complaint_themes text
  last_updated date
}
 
Table com_market_mapping {
  id integer [pk]
  firm_id text [ref: > firms.firm_id]
  snapshot_date date
  competitor_name text
  competitor_city text
  competitor_state text
  primary_practice_areas text
  estimated_size text
  estimated_annual_revenue real
  attorney_count_estimate int
  google_rating real
  google_review_count int
  geographic_overlap_pct real
  market_position text
  competitive_threat_level text
  notes text
}
 
TableGroup Financials {
  fin_case_unit_economics
  fin_pnl_breakdown
  fin_practice_area_profitability
}
 
TableGroup Cases {
  cas_top_25_cases
  cas_cases_opened_over_time
  cas_closed_cases
  cas_current_inventory
  cas_inventory_aging
  cas_costs_over_time
  cas_win_trial_rate
}
 
TableGroup Litigation {
  lit_profitability
  lit_volume_trends
  lit_case_timing
}
 
TableGroup Personnel {
  per_employee_census
  per_employee_productivity
  per_key_person_risk
  per_org_chart
  per_senior_junior_ratios
}
 
TableGroup Marketing {
  mkt_spend_mix
  mkt_lead_gen_source
  mkt_performance
}
 
TableGroup Intake {
  int_funnel
  int_workflow
}
 
TableGroup Referrals {
  ref_outbound
  ref_inbound
}
 
TableGroup Geography {
  geo_office_performance
  geo_office_overview
  geo_footprint
}
 
TableGroup Technology {
  tec_tools
}
 
TableGroup Competition {
  com_competitor_reviews
  com_market_mapping
}