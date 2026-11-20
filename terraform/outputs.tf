output "source_bucket" {
  value = aws_s3_bucket.source.bucket
}

output "database_endpoint" {
  value = aws_db_instance.orders.endpoint
}
