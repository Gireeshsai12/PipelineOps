variable "region" {
  type        = string
  description = "AWS region containing the application VPC."
  default     = "us-east-1"
}

variable "name" {
  type        = string
  description = "Prefix for the database and its networking resources."
  default     = "pipelineops"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique order source bucket name."
}

variable "vpc_id" {
  type        = string
  description = "Existing application VPC."
}

variable "application_security_group_id" {
  type        = string
  description = "Existing client security group in the same VPC."
}

variable "private_subnet_ids" {
  type        = set(string)
  description = "Existing private subnet IDs across at least two Availability Zones."
  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Supply at least two private subnets in separate Availability Zones."
  }
}

variable "instance_class" {
  type        = string
  description = "RDS instance class."
  default     = "db.t4g.micro"
}

variable "allocated_storage_gib" {
  type        = number
  description = "RDS storage allocation in GiB."
  default     = 20
}

variable "multi_az" {
  type        = bool
  description = "Enable a synchronous multi-AZ standby."
  default     = false
}
