terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.94.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_s3_bucket" "source" {
  bucket        = var.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "source" {
  bucket = aws_s3_bucket.source.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_db_subnet_group" "orders" {
  name       = "${var.name}-postgres"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "orders" {
  name        = "${var.name}-postgres"
  description = "PostgreSQL access from application security group"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.orders.id
  referenced_security_group_id = var.application_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "orders" {
  identifier                   = var.name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.instance_class
  allocated_storage            = var.allocated_storage_gib
  storage_encrypted            = true
  publicly_accessible          = false
  multi_az                     = var.multi_az
  db_name                      = "pipeline"
  username                     = "pipeline_admin"
  manage_master_user_password  = true
  db_subnet_group_name         = aws_db_subnet_group.orders.name
  vpc_security_group_ids       = [aws_security_group.orders.id]
  backup_retention_period      = 7
  deletion_protection          = true
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${var.name}-final"
  auto_minor_version_upgrade   = true
  copy_tags_to_snapshot        = true
  performance_insights_enabled = false
}
