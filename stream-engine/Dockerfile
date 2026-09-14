# Build context is the REPO ROOT (see docker-compose.yml) so ../proto resolves for codegen.
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY proto ./proto
COPY stream-engine/pom.xml ./stream-engine/pom.xml
RUN mvn -q -B -f stream-engine/pom.xml dependency:go-offline
COPY stream-engine/src ./stream-engine/src
RUN mvn -q -B -f stream-engine/pom.xml -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/stream-engine/target/stream-engine-*.jar app.jar
EXPOSE 8081
# MaxRAMPercentage is a share of the CONTAINER limit, so compose sets mem_limit for every
# service. Without a limit it is a share of the whole Docker VM and three JVMs each think
# they may take most of it. RocksDB keeps its block cache and memtables OFF heap, so the JVM cannot have most of the container.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=55", "-jar", "app.jar"]
