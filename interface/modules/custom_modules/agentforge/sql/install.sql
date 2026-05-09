#IfNotTable agentforge_documents
CREATE TABLE IF NOT EXISTS `agentforge_documents` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `pid` BIGINT NOT NULL,
    `encounter_id` BIGINT DEFAULT NULL,
    `openemr_document_id` BIGINT DEFAULT NULL,
    `document_type` VARCHAR(32) NOT NULL,
    `original_filename` VARCHAR(255) NOT NULL,
    `mime_type` VARCHAR(120) NOT NULL,
    `file_hash` CHAR(64) NOT NULL,
    `extraction_status` VARCHAR(32) NOT NULL DEFAULT 'pending',
    `extraction_trace_id` VARCHAR(120) DEFAULT NULL,
    `extraction_summary` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_agentforge_documents_pid` (`pid`),
    KEY `idx_agentforge_documents_openemr_document_id` (`openemr_document_id`),
    KEY `idx_agentforge_documents_type_status` (`document_type`, `extraction_status`)
) ENGINE=InnoDB COMMENT='AgentForge OpenEMR document extraction tracking';
#EndIf

#IfNotTable agentforge_chart_writebacks
CREATE TABLE IF NOT EXISTS `agentforge_chart_writebacks` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `pid` BIGINT NOT NULL,
    `agentforge_document_id` BIGINT NOT NULL,
    `openemr_document_id` BIGINT DEFAULT NULL,
    `agentforge_fact_id` BIGINT DEFAULT NULL,
    `target_table` VARCHAR(64) NOT NULL,
    `target_field` VARCHAR(120) NOT NULL DEFAULT '',
    `target_record_id` VARCHAR(120) NOT NULL DEFAULT '',
    `old_value` TEXT DEFAULT NULL,
    `new_value` TEXT DEFAULT NULL,
    `action` VARCHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `trace_id` VARCHAR(120) DEFAULT NULL,
    `message` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_agentforge_writebacks_pid` (`pid`),
    KEY `idx_agentforge_writebacks_document` (`agentforge_document_id`),
    KEY `idx_agentforge_writebacks_fact` (`agentforge_fact_id`)
) ENGINE=InnoDB COMMENT='AgentForge chart writeback audit log';
#EndIf

#IfNotTable agentforge_extracted_facts
CREATE TABLE IF NOT EXISTS `agentforge_extracted_facts` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `agentforge_document_id` BIGINT NOT NULL,
    `pid` BIGINT NOT NULL,
    `openemr_document_id` BIGINT DEFAULT NULL,
    `fact_type` VARCHAR(64) NOT NULL,
    `label` VARCHAR(160) NOT NULL,
    `value` TEXT NOT NULL,
    `unit` VARCHAR(64) DEFAULT '',
    `reference_range` VARCHAR(120) DEFAULT '',
    `abnormal_flag` VARCHAR(64) DEFAULT '',
    `recorded_at` VARCHAR(64) DEFAULT '',
    `confidence` DECIMAL(5,4) DEFAULT 0.0000,
    `citation_json` TEXT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_agentforge_facts_document` (`agentforge_document_id`),
    KEY `idx_agentforge_facts_pid` (`pid`),
    KEY `idx_agentforge_facts_type` (`fact_type`)
) ENGINE=InnoDB COMMENT='AgentForge source-cited extracted facts';
#EndIf
