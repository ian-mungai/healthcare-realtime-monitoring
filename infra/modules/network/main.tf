data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "mwaa" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_vpc"
    }
  )
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.mwaa.id
  cidr_block              = "10.20.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_public_a"
    }
  )
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.mwaa.id
  cidr_block              = "10.20.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_public_b"
    }
  )
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.mwaa.id
  cidr_block        = "10.20.11.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_private_a"
    }
  )
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.mwaa.id
  cidr_block        = "10.20.12.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_private_b"
    }
  )
}

resource "aws_internet_gateway" "mwaa" {
  vpc_id = aws_vpc.mwaa.id

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_igw"
    }
  )
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_nat_eip"
    }
  )
}

resource "aws_nat_gateway" "mwaa" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_a.id

  depends_on = [
    aws_internet_gateway.mwaa
  ]

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_nat"
    }
  )
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.mwaa.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.mwaa.id
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_public_rt"
    }
  )
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.mwaa.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.mwaa.id
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_private_rt"
    }
  )
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "mwaa" {
  name        = "${var.name}_sg"
  description = "Security group for Amazon MWAA"
  vpc_id      = aws_vpc.mwaa.id

  ingress {
    description = "Allow MWAA internal traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    description = "Allow outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name}_sg"
    }
  )
}