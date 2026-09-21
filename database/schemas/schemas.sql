--
-- PostgreSQL database dump
--

\restrict K2ie2LRaUqeEH42mr8QpUhvgcFU7RLOEyz52472zoS7MfICgANR67xWSa2CUc7a

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
-- Name: manufacturers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.manufacturers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
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
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


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
-- Name: ix_locations_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_hospital_id ON public.locations USING btree (hospital_id);


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
-- Name: manufacturers trg_manufacturers_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_manufacturers_updated_at BEFORE UPDATE ON public.manufacturers FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: organizations trg_organizations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_organizations_updated_at BEFORE UPDATE ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


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
-- PostgreSQL database dump complete
--

\unrestrict K2ie2LRaUqeEH42mr8QpUhvgcFU7RLOEyz52472zoS7MfICgANR67xWSa2CUc7a