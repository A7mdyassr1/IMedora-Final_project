--
-- PostgreSQL database dump
--

\restrict 1ixe3vc7ctTwzneTepQiFaaiwtNmmprcAZacsvl1NF7t3wayAhpU07qrBwsv5Bs

-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: audit_action; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.audit_action AS ENUM (
    'insert',
    'update',
    'delete'
);


--
-- Name: device_criticality; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.device_criticality AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);


--
-- Name: device_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.device_status AS ENUM (
    'active',
    'under_maintenance',
    'out_of_service',
    'decommissioned'
);


--
-- Name: qa_record_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.qa_record_type AS ENUM (
    'inspection',
    'calibration',
    'compliance'
);


--
-- Name: qa_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.qa_status AS ENUM (
    'pass',
    'fail',
    'pending'
);


--
-- Name: risk_level; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.risk_level AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);


--
-- Name: ticket_priority; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ticket_priority AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);


--
-- Name: ticket_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ticket_status AS ENUM (
    'open',
    'assigned',
    'in_progress',
    'waiting_for_parts',
    'resolved',
    'closed',
    'cancelled'
);


--
-- Name: adjust_part_inventory_on_usage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.adjust_part_inventory_on_usage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_hospital_id UUID;
            v_rows_affected INT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = NEW.maintenance_record_id;

                UPDATE part_inventory
                SET quantity_on_hand = quantity_on_hand - NEW.quantity
                WHERE hospital_id = v_hospital_id AND part_id = NEW.part_id;
                GET DIAGNOSTICS v_rows_affected = ROW_COUNT;

                IF v_rows_affected = 0 THEN
                    RAISE EXCEPTION
                        'No part_inventory row for part % at hospital % - cannot record usage of a part that was never stocked there',
                        NEW.part_id, v_hospital_id;
                END IF;
                RETURN NEW;

            ELSIF TG_OP = 'UPDATE' THEN
                IF NEW.quantity <> OLD.quantity THEN
                    SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = NEW.maintenance_record_id;
                    UPDATE part_inventory
                    SET quantity_on_hand = quantity_on_hand - (NEW.quantity - OLD.quantity)
                    WHERE hospital_id = v_hospital_id AND part_id = NEW.part_id;
                END IF;
                RETURN NEW;

            ELSIF TG_OP = 'DELETE' THEN
                SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = OLD.maintenance_record_id;
                UPDATE part_inventory
                SET quantity_on_hand = quantity_on_hand + OLD.quantity
                WHERE hospital_id = v_hospital_id AND part_id = OLD.part_id;
                RETURN OLD;
            END IF;

            RETURN NULL;
        END;
        $$;


--
-- Name: refresh_device_current_risk_level(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.refresh_device_current_risk_level() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_device_id UUID;
            v_latest_risk risk_level;
        BEGIN
            v_device_id := COALESCE(NEW.device_id, OLD.device_id);

            SELECT risk_level INTO v_latest_risk
            FROM risk_assessments
            WHERE device_id = v_device_id
            ORDER BY assessed_at DESC
            LIMIT 1;

            UPDATE devices SET current_risk_level = v_latest_risk WHERE id = v_device_id;

            RETURN COALESCE(NEW, OLD);
        END;
        $$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid,
    ticket_id uuid,
    maintenance_record_id uuid,
    uploaded_by uuid NOT NULL,
    file_url character varying(500) NOT NULL,
    file_name character varying(255),
    mime_type character varying(100),
    file_size_bytes bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_attachment_exactly_one_parent CHECK ((((
CASE
    WHEN (device_id IS NOT NULL) THEN 1
    ELSE 0
END +
CASE
    WHEN (ticket_id IS NOT NULL) THEN 1
    ELSE 0
END) +
CASE
    WHEN (maintenance_record_id IS NOT NULL) THEN 1
    ELSE 0
END) = 1)),
    CONSTRAINT ck_attachment_size_non_negative CHECK (((file_size_bytes IS NULL) OR (file_size_bytes >= 0)))
);


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid,
    table_name character varying(100) NOT NULL,
    record_id uuid NOT NULL,
    action public.audit_action NOT NULL,
    old_values jsonb,
    new_values jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    hospital_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_models (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    manufacturer_id uuid NOT NULL,
    device_category_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    department_id uuid NOT NULL,
    location_id uuid,
    device_model_id uuid NOT NULL,
    device_code character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    serial_number character varying(255),
    qr_identifier character varying(255) NOT NULL,
    status public.device_status DEFAULT 'active'::public.device_status NOT NULL,
    criticality public.device_criticality DEFAULT 'medium'::public.device_criticality NOT NULL,
    installation_date date,
    warranty_expiry date,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    next_maintenance_due_date date,
    current_risk_level public.risk_level,
    CONSTRAINT ck_device_warranty_after_installation CHECK (((warranty_expiry IS NULL) OR (installation_date IS NULL) OR (warranty_expiry >= installation_date)))
);


--
-- Name: hospitals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hospitals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    code character varying(50) NOT NULL,
    address character varying(500),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    hospital_id uuid NOT NULL,
    building character varying(100),
    floor character varying(50),
    room character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: maintenance_parts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_parts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    maintenance_record_id uuid NOT NULL,
    part_id uuid NOT NULL,
    quantity integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_maintenance_parts_quantity_positive CHECK ((quantity > 0))
);


--
-- Name: maintenance_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid NOT NULL,
    maintenance_type_id uuid NOT NULL,
    ticket_id uuid,
    schedule_id uuid,
    performed_by uuid NOT NULL,
    description text NOT NULL,
    performed_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: maintenance_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_schedules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid NOT NULL,
    maintenance_type_id uuid NOT NULL,
    frequency_days integer NOT NULL,
    next_due_date date NOT NULL,
    last_performed_date date,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_schedule_frequency_positive CHECK ((frequency_days > 0))
);


--
-- Name: maintenance_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_tickets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid NOT NULL,
    reported_by uuid NOT NULL,
    problem_description text NOT NULL,
    priority public.ticket_priority DEFAULT 'medium'::public.ticket_priority NOT NULL,
    status public.ticket_status DEFAULT 'open'::public.ticket_status NOT NULL,
    resolved_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_ticket_resolved_after_created CHECK (((resolved_at IS NULL) OR (resolved_at >= created_at))),
    CONSTRAINT ck_ticket_resolved_status_has_timestamp CHECK (((status <> ALL (ARRAY['resolved'::public.ticket_status, 'closed'::public.ticket_status])) OR (resolved_at IS NOT NULL)))
);


--
-- Name: maintenance_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_types (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: manufacturers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.manufacturers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    related_ticket_id uuid,
    title character varying(255) NOT NULL,
    body text,
    notification_type character varying(50),
    is_read boolean DEFAULT false NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_notification_read_after_created CHECK (((read_at IS NULL) OR (read_at >= created_at))),
    CONSTRAINT ck_notification_read_has_timestamp CHECK (((NOT is_read) OR (read_at IS NOT NULL)))
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    code character varying(50) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: part_inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.part_inventory (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    part_id uuid NOT NULL,
    quantity_on_hand integer DEFAULT 0 NOT NULL,
    reorder_threshold integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_inventory_quantity_non_negative CHECK ((quantity_on_hand >= 0)),
    CONSTRAINT ck_inventory_reorder_non_negative CHECK (((reorder_threshold IS NULL) OR (reorder_threshold >= 0)))
);


--
-- Name: parts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    part_number character varying(100) NOT NULL,
    unit character varying(20) DEFAULT 'piece'::character varying NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: qa_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid NOT NULL,
    performed_by uuid NOT NULL,
    record_type public.qa_record_type NOT NULL,
    status public.qa_status DEFAULT 'pending'::public.qa_status NOT NULL,
    findings text,
    performed_at timestamp with time zone DEFAULT now() NOT NULL,
    next_due_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_qa_next_due_after_performed CHECK (((next_due_date IS NULL) OR (next_due_date >= (performed_at)::date)))
);


--
-- Name: risk_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_assessments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    device_id uuid NOT NULL,
    assessed_by uuid NOT NULL,
    risk_level public.risk_level NOT NULL,
    notes text,
    assessed_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ticket_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ticket_assignments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    ticket_id uuid NOT NULL,
    user_id uuid NOT NULL,
    assigned_at timestamp with time zone DEFAULT now() NOT NULL,
    unassigned_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_assignment_unassigned_after_assigned CHECK (((unassigned_at IS NULL) OR (unassigned_at >= assigned_at)))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    department_id uuid,
    role_id uuid NOT NULL,
    full_name character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: attachments attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: device_categories device_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_categories
    ADD CONSTRAINT device_categories_name_key UNIQUE (name);


--
-- Name: device_categories device_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_categories
    ADD CONSTRAINT device_categories_pkey PRIMARY KEY (id);


--
-- Name: device_models device_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_models
    ADD CONSTRAINT device_models_pkey PRIMARY KEY (id);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (id);


--
-- Name: devices devices_qr_identifier_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_qr_identifier_key UNIQUE (qr_identifier);


--
-- Name: hospitals hospitals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitals
    ADD CONSTRAINT hospitals_pkey PRIMARY KEY (id);


--
-- Name: locations locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_pkey PRIMARY KEY (id);


--
-- Name: maintenance_parts maintenance_parts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_parts
    ADD CONSTRAINT maintenance_parts_pkey PRIMARY KEY (id);


--
-- Name: maintenance_records maintenance_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_pkey PRIMARY KEY (id);


--
-- Name: maintenance_schedules maintenance_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_pkey PRIMARY KEY (id);


--
-- Name: maintenance_tickets maintenance_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT maintenance_tickets_pkey PRIMARY KEY (id);


--
-- Name: maintenance_types maintenance_types_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_types
    ADD CONSTRAINT maintenance_types_name_key UNIQUE (name);


--
-- Name: maintenance_types maintenance_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_types
    ADD CONSTRAINT maintenance_types_pkey PRIMARY KEY (id);


--
-- Name: manufacturers manufacturers_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturers
    ADD CONSTRAINT manufacturers_name_key UNIQUE (name);


--
-- Name: manufacturers manufacturers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturers
    ADD CONSTRAINT manufacturers_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_code_key UNIQUE (code);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: part_inventory part_inventory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part_inventory
    ADD CONSTRAINT part_inventory_pkey PRIMARY KEY (id);


--
-- Name: parts parts_part_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parts
    ADD CONSTRAINT parts_part_number_key UNIQUE (part_number);


--
-- Name: parts parts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parts
    ADD CONSTRAINT parts_pkey PRIMARY KEY (id);


--
-- Name: qa_records qa_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_records
    ADD CONSTRAINT qa_records_pkey PRIMARY KEY (id);


--
-- Name: risk_assessments risk_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_pkey PRIMARY KEY (id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: ticket_assignments ticket_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_assignments
    ADD CONSTRAINT ticket_assignments_pkey PRIMARY KEY (id);


--
-- Name: departments uq_department_hospital_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT uq_department_hospital_name UNIQUE (hospital_id, name);


--
-- Name: devices uq_device_hospital_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT uq_device_hospital_code UNIQUE (hospital_id, device_code);


--
-- Name: device_models uq_device_model_manufacturer_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_models
    ADD CONSTRAINT uq_device_model_manufacturer_name UNIQUE (manufacturer_id, name);


--
-- Name: hospitals uq_hospital_org_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitals
    ADD CONSTRAINT uq_hospital_org_code UNIQUE (organization_id, code);


--
-- Name: part_inventory uq_inventory_hospital_part; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part_inventory
    ADD CONSTRAINT uq_inventory_hospital_part UNIQUE (hospital_id, part_id);


--
-- Name: maintenance_parts uq_record_part; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_parts
    ADD CONSTRAINT uq_record_part UNIQUE (maintenance_record_id, part_id);


--
-- Name: maintenance_schedules uq_schedule_device_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT uq_schedule_device_type UNIQUE (device_id, maintenance_type_id);


--
-- Name: maintenance_schedules uq_schedule_id_device_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT uq_schedule_id_device_type UNIQUE (id, device_id, maintenance_type_id);


--
-- Name: maintenance_tickets uq_ticket_id_device; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT uq_ticket_id_device UNIQUE (id, device_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_attachments_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_device_id ON public.attachments USING btree (device_id);


--
-- Name: ix_attachments_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_hospital_id ON public.attachments USING btree (hospital_id);


--
-- Name: ix_attachments_maintenance_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_maintenance_record_id ON public.attachments USING btree (maintenance_record_id);


--
-- Name: ix_attachments_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_organization_id ON public.attachments USING btree (organization_id);


--
-- Name: ix_attachments_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_ticket_id ON public.attachments USING btree (ticket_id);


--
-- Name: ix_attachments_uploaded_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_uploaded_by ON public.attachments USING btree (uploaded_by);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_audit_logs_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_organization_id ON public.audit_logs USING btree (organization_id);


--
-- Name: ix_audit_logs_table_record; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_table_record ON public.audit_logs USING btree (table_name, record_id);


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_device_models_device_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_device_models_device_category_id ON public.device_models USING btree (device_category_id);


--
-- Name: ix_devices_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_devices_department_id ON public.devices USING btree (department_id);


--
-- Name: ix_devices_device_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_devices_device_model_id ON public.devices USING btree (device_model_id);


--
-- Name: ix_devices_location_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_devices_location_id ON public.devices USING btree (location_id);


--
-- Name: ix_devices_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_devices_organization_id ON public.devices USING btree (organization_id);


--
-- Name: ix_devices_serial_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_devices_serial_number ON public.devices USING btree (serial_number);


--
-- Name: ix_inventory_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_organization_id ON public.part_inventory USING btree (organization_id);


--
-- Name: ix_locations_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_hospital_id ON public.locations USING btree (hospital_id);


--
-- Name: ix_maintenance_parts_part_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_maintenance_parts_part_id ON public.maintenance_parts USING btree (part_id);


--
-- Name: ix_maintenance_schedules_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_maintenance_schedules_hospital_id ON public.maintenance_schedules USING btree (hospital_id);


--
-- Name: ix_maintenance_schedules_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_maintenance_schedules_organization_id ON public.maintenance_schedules USING btree (organization_id);


--
-- Name: ix_notifications_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_organization_id ON public.notifications USING btree (organization_id);


--
-- Name: ix_notifications_related_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_related_ticket_id ON public.notifications USING btree (related_ticket_id);


--
-- Name: ix_notifications_user_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_unread ON public.notifications USING btree (user_id, is_read);


--
-- Name: ix_part_inventory_part_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_part_inventory_part_id ON public.part_inventory USING btree (part_id);


--
-- Name: ix_qa_records_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_records_device_id ON public.qa_records USING btree (device_id);


--
-- Name: ix_qa_records_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_records_hospital_id ON public.qa_records USING btree (hospital_id);


--
-- Name: ix_qa_records_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_records_organization_id ON public.qa_records USING btree (organization_id);


--
-- Name: ix_qa_records_performed_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_records_performed_by ON public.qa_records USING btree (performed_by);


--
-- Name: ix_records_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_device_id ON public.maintenance_records USING btree (device_id);


--
-- Name: ix_records_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_hospital_id ON public.maintenance_records USING btree (hospital_id);


--
-- Name: ix_records_maintenance_type_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_maintenance_type_id ON public.maintenance_records USING btree (maintenance_type_id);


--
-- Name: ix_records_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_organization_id ON public.maintenance_records USING btree (organization_id);


--
-- Name: ix_records_performed_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_performed_by ON public.maintenance_records USING btree (performed_by);


--
-- Name: ix_records_schedule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_schedule_id ON public.maintenance_records USING btree (schedule_id);


--
-- Name: ix_records_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_records_ticket_id ON public.maintenance_records USING btree (ticket_id);


--
-- Name: ix_risk_assessments_assessed_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_assessed_by ON public.risk_assessments USING btree (assessed_by);


--
-- Name: ix_risk_assessments_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_device_id ON public.risk_assessments USING btree (device_id);


--
-- Name: ix_risk_assessments_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_hospital_id ON public.risk_assessments USING btree (hospital_id);


--
-- Name: ix_risk_assessments_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_organization_id ON public.risk_assessments USING btree (organization_id);


--
-- Name: ix_ticket_assignments_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ticket_assignments_ticket_id ON public.ticket_assignments USING btree (ticket_id);


--
-- Name: ix_ticket_assignments_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ticket_assignments_user_id ON public.ticket_assignments USING btree (user_id);


--
-- Name: ix_tickets_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tickets_device_id ON public.maintenance_tickets USING btree (device_id);


--
-- Name: ix_tickets_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tickets_hospital_id ON public.maintenance_tickets USING btree (hospital_id);


--
-- Name: ix_tickets_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tickets_organization_id ON public.maintenance_tickets USING btree (organization_id);


--
-- Name: ix_tickets_reported_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tickets_reported_by ON public.maintenance_tickets USING btree (reported_by);


--
-- Name: ix_tickets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tickets_status ON public.maintenance_tickets USING btree (status);


--
-- Name: ix_users_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_department_id ON public.users USING btree (department_id);


--
-- Name: ix_users_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_hospital_id ON public.users USING btree (hospital_id);


--
-- Name: ix_users_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_organization_id ON public.users USING btree (organization_id);


--
-- Name: ix_users_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_role_id ON public.users USING btree (role_id);


--
-- Name: uq_active_assignment; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_active_assignment ON public.ticket_assignments USING btree (ticket_id, user_id) WHERE (unassigned_at IS NULL);


--
-- Name: attachments trg_attachments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_attachments_updated_at BEFORE UPDATE ON public.attachments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: departments trg_departments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_departments_updated_at BEFORE UPDATE ON public.departments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: device_categories trg_device_categories_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_device_categories_updated_at BEFORE UPDATE ON public.device_categories FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: device_models trg_device_models_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_device_models_updated_at BEFORE UPDATE ON public.device_models FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: devices trg_devices_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_devices_updated_at BEFORE UPDATE ON public.devices FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: hospitals trg_hospitals_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_hospitals_updated_at BEFORE UPDATE ON public.hospitals FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: locations trg_locations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_locations_updated_at BEFORE UPDATE ON public.locations FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: maintenance_parts trg_maintenance_parts_adjust_inventory; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_maintenance_parts_adjust_inventory AFTER INSERT OR DELETE OR UPDATE OF quantity ON public.maintenance_parts FOR EACH ROW EXECUTE FUNCTION public.adjust_part_inventory_on_usage();


--
-- Name: maintenance_parts trg_maintenance_parts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_maintenance_parts_updated_at BEFORE UPDATE ON public.maintenance_parts FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: maintenance_schedules trg_maintenance_schedules_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_maintenance_schedules_updated_at BEFORE UPDATE ON public.maintenance_schedules FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: maintenance_types trg_maintenance_types_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_maintenance_types_updated_at BEFORE UPDATE ON public.maintenance_types FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: manufacturers trg_manufacturers_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_manufacturers_updated_at BEFORE UPDATE ON public.manufacturers FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: notifications trg_notifications_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notifications_updated_at BEFORE UPDATE ON public.notifications FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: organizations trg_organizations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_organizations_updated_at BEFORE UPDATE ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: part_inventory trg_part_inventory_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_part_inventory_updated_at BEFORE UPDATE ON public.part_inventory FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: parts trg_parts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_parts_updated_at BEFORE UPDATE ON public.parts FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: qa_records trg_qa_records_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_qa_records_updated_at BEFORE UPDATE ON public.qa_records FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: maintenance_records trg_records_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_records_updated_at BEFORE UPDATE ON public.maintenance_records FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: risk_assessments trg_risk_assessments_refresh_device; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_assessments_refresh_device AFTER INSERT OR DELETE OR UPDATE ON public.risk_assessments FOR EACH ROW EXECUTE FUNCTION public.refresh_device_current_risk_level();


--
-- Name: risk_assessments trg_risk_assessments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_assessments_updated_at BEFORE UPDATE ON public.risk_assessments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: roles trg_roles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_roles_updated_at BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: ticket_assignments trg_ticket_assignments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_ticket_assignments_updated_at BEFORE UPDATE ON public.ticket_assignments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: maintenance_tickets trg_tickets_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tickets_updated_at BEFORE UPDATE ON public.maintenance_tickets FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: users trg_users_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: attachments attachments_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: attachments attachments_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: attachments attachments_maintenance_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_maintenance_record_id_fkey FOREIGN KEY (maintenance_record_id) REFERENCES public.maintenance_records(id) ON DELETE RESTRICT;


--
-- Name: attachments attachments_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: attachments attachments_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.maintenance_tickets(id) ON DELETE RESTRICT;


--
-- Name: attachments attachments_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: audit_logs audit_logs_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: departments departments_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: device_models device_models_device_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_models
    ADD CONSTRAINT device_models_device_category_id_fkey FOREIGN KEY (device_category_id) REFERENCES public.device_categories(id) ON DELETE RESTRICT;


--
-- Name: device_models device_models_manufacturer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_models
    ADD CONSTRAINT device_models_manufacturer_id_fkey FOREIGN KEY (manufacturer_id) REFERENCES public.manufacturers(id) ON DELETE RESTRICT;


--
-- Name: devices devices_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE RESTRICT;


--
-- Name: devices devices_device_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_device_model_id_fkey FOREIGN KEY (device_model_id) REFERENCES public.device_models(id) ON DELETE RESTRICT;


--
-- Name: devices devices_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: devices devices_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;


--
-- Name: devices devices_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records fk_record_schedule_same_device_and_type; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT fk_record_schedule_same_device_and_type FOREIGN KEY (schedule_id, device_id, maintenance_type_id) REFERENCES public.maintenance_schedules(id, device_id, maintenance_type_id) ON DELETE RESTRICT;


--
-- Name: maintenance_records fk_record_ticket_same_device; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT fk_record_ticket_same_device FOREIGN KEY (ticket_id, device_id) REFERENCES public.maintenance_tickets(id, device_id) ON DELETE RESTRICT;


--
-- Name: hospitals hospitals_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitals
    ADD CONSTRAINT hospitals_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: locations locations_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE CASCADE;


--
-- Name: maintenance_parts maintenance_parts_maintenance_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_parts
    ADD CONSTRAINT maintenance_parts_maintenance_record_id_fkey FOREIGN KEY (maintenance_record_id) REFERENCES public.maintenance_records(id) ON DELETE CASCADE;


--
-- Name: maintenance_parts maintenance_parts_part_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_parts
    ADD CONSTRAINT maintenance_parts_part_id_fkey FOREIGN KEY (part_id) REFERENCES public.parts(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records maintenance_records_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records maintenance_records_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records maintenance_records_maintenance_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_maintenance_type_id_fkey FOREIGN KEY (maintenance_type_id) REFERENCES public.maintenance_types(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records maintenance_records_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: maintenance_records maintenance_records_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_records
    ADD CONSTRAINT maintenance_records_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: maintenance_schedules maintenance_schedules_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: maintenance_schedules maintenance_schedules_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: maintenance_schedules maintenance_schedules_maintenance_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_maintenance_type_id_fkey FOREIGN KEY (maintenance_type_id) REFERENCES public.maintenance_types(id) ON DELETE RESTRICT;


--
-- Name: maintenance_schedules maintenance_schedules_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: maintenance_tickets maintenance_tickets_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT maintenance_tickets_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: maintenance_tickets maintenance_tickets_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT maintenance_tickets_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: maintenance_tickets maintenance_tickets_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT maintenance_tickets_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: maintenance_tickets maintenance_tickets_reported_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tickets
    ADD CONSTRAINT maintenance_tickets_reported_by_fkey FOREIGN KEY (reported_by) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: notifications notifications_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_related_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_related_ticket_id_fkey FOREIGN KEY (related_ticket_id) REFERENCES public.maintenance_tickets(id) ON DELETE SET NULL;


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: part_inventory part_inventory_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part_inventory
    ADD CONSTRAINT part_inventory_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: part_inventory part_inventory_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part_inventory
    ADD CONSTRAINT part_inventory_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: part_inventory part_inventory_part_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part_inventory
    ADD CONSTRAINT part_inventory_part_id_fkey FOREIGN KEY (part_id) REFERENCES public.parts(id) ON DELETE RESTRICT;


--
-- Name: qa_records qa_records_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_records
    ADD CONSTRAINT qa_records_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: qa_records qa_records_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_records
    ADD CONSTRAINT qa_records_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: qa_records qa_records_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_records
    ADD CONSTRAINT qa_records_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: qa_records qa_records_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_records
    ADD CONSTRAINT qa_records_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: risk_assessments risk_assessments_assessed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_assessed_by_fkey FOREIGN KEY (assessed_by) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: risk_assessments risk_assessments_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON DELETE RESTRICT;


--
-- Name: risk_assessments risk_assessments_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: risk_assessments risk_assessments_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: ticket_assignments ticket_assignments_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_assignments
    ADD CONSTRAINT ticket_assignments_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.maintenance_tickets(id) ON DELETE CASCADE;


--
-- Name: ticket_assignments ticket_assignments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_assignments
    ADD CONSTRAINT ticket_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: users users_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: users users_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id) ON DELETE RESTRICT;


--
-- Name: users users_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: users users_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict 1ixe3vc7ctTwzneTepQiFaaiwtNmmprcAZacsvl1NF7t3wayAhpU07qrBwsv5Bs

