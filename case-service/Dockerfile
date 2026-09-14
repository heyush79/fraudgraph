FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:17-jre
# curl is only here so the compose healthcheck can hit /actuator/health
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/target/case-service-*.jar app.jar
EXPOSE 8082
# MaxRAMPercentage is a share of the CONTAINER limit, so compose sets mem_limit for every
# service. Without a limit it is a share of the whole Docker VM and three JVMs each think
# they may take most of it. no off-heap store here, so the JVM can have more of its container.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=65", "-jar", "app.jar"]
